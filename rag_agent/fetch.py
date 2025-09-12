from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import List, Dict, Tuple, Set
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PWTimeout, Page

from rag_agent.models import Action, Plan, Metrics, StopConfig, WalkState, Snapshot, Anchor, ReflectOutput
from rag_agent.parse import (
    html_to_markdown,
    extract_anchors,
    extract_jsonld_objects,
    bootstrap_site_hints,
    same_site,
)
from rag_agent.llm import plan_site_walk, reflect_and_extract
from rag_agent.storage import upsert_org, upsert_project, load_orgs, load_projects, save_orgs, save_projects

logger = logging.getLogger("rag_agent.fetch")

CLICK_TIMEOUT = 5000
NAV_TIMEOUT = 20000
SCROLL_PAUSE_MS = 300


def _allowed(url: str, plan: Plan) -> bool:
    if plan.same_domain_only:
        if not same_site(url, plan.start_url):
            # allow explicit allowlist overrides
            host = urlparse(url).netloc.lower()
            for al in plan.domain_allowlist:
                if host == al or host.endswith("." + al):
                    return True
            return False
    return True


async def _grace_goto(page: Page, url: str) -> None:
    try:
        await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT)
    except PWTimeout:
        # Try at least DOM-ready
        await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)


async def _snapshot_page(page: Page, url: str) -> Snapshot:
    # Stabilize content a bit
    try:
        await page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass

    html = await page.content()
    hints = bootstrap_site_hints(url, html)
    md = html_to_markdown(html)
    jsonld = extract_jsonld_objects(html, url)
    anchors = extract_anchors(html, url, limit=200)

    # Truncate HTML to keep snapshots light
    html_trunc = html if len(html) <= 120_000 else html[:120_000]

    return Snapshot(
        url=url,
        title=hints.get("title"),
        site_name=hints.get("site_name"),
        meta_description=hints.get("meta_description"),
        markdown=md,
        html_truncated=html_trunc,
        jsonld_objects=jsonld,
        anchors=[Anchor(text=a.get("text"), href=a["href"]) for a in anchors],
    )


async def _scroll_to_bottom(page: Page) -> None:
    try:
        await page.evaluate(
            """async () => {
                let last = 0;
                for (let i=0;i<10;i++){
                    window.scrollTo(0, document.body.scrollHeight);
                    await new Promise(r=>setTimeout(r, %d));
                    const h = document.body.scrollHeight;
                    if (h === last) break;
                    last = h;
                }
            }""" % SCROLL_PAUSE_MS
        )
    except Exception:
        pass


async def navigate_with_plan(url: str, stop: StopConfig | None = None) -> Tuple[WalkState, List[Snapshot]]:
    """
    Crawl within budgets, reflect each page, collect org & project info.
    Returns (walk_state, all_snapshots).
    """
    plan = plan_site_walk(url)
    if stop is not None:
        plan.stop = stop

    visited: Set[str] = set()
    frontier: List[str] = [plan.start_url]
    snapshots: List[Snapshot] = []
    metrics = Metrics()

    orgs = load_orgs()
    projs = load_projects()
    org_record = None  # last upserted org

    t0 = time.time()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            while frontier:
                # hard stops
                if metrics.actions_total >= plan.stop.hard.max_actions:
                    logger.info("Stopping: reached max_actions=%d", plan.stop.hard.max_actions)
                    break
                if time.time() - t0 >= plan.stop.hard.time_budget_s:
                    logger.info("Stopping: reached time budget (s)=%d", plan.stop.hard.time_budget_s)
                    break

                current = frontier.pop(0)
                if current in visited:
                    continue
                if not _allowed(current, plan):
                    continue

                logger.info("Visiting: %s", current)
                await _grace_goto(page, current)
                snap = await _snapshot_page(page, current)
                snapshots.append(snap)
                visited.add(current)
                metrics.pages_visited += 1

                # reflect and extract (robust to schema hiccups)
                try:
                    reflect = reflect_and_extract(plan, [snap])
                except Exception as e:
                    logger.warning("Reflect failed on %s: %s", current, e)
                    reflect = ReflectOutput(done=False, coverage="partial", justification="fallback after parse error")

                actions = reflect.actions or []
                goto_urls = [u for u in (reflect.goto_urls or []) if _allowed(u, plan)]

                # Basic action execution (scroll only)
                performed = 1  # count this step as an action
                for a in actions:
                    if a.type == "SCROLL":
                        await _scroll_to_bottom(page)
                        performed += 1

                # Upsert org & projects as we go (org only first time or if better data)
                if reflect.organization:
                    org_record = upsert_org(orgs, reflect.organization)
                    save_orgs(orgs)

                if org_record:
                    for p in reflect.projects or []:
                        upsert_project(
                            projs,
                            organization_id=org_record["organization_id"],
                            name=p.name or "",
                            description=p.description or "",
                            source_url=p.source_url or snap.url,
                            ensure_min_chars=600,
                            site_markdown=snap.markdown or "",
                        )
                    save_projects(projs)

                # Frontier management
                new_links = 0
                for u in goto_urls:
                    if u not in visited and u not in frontier:
                        frontier.append(u)
                        new_links += 1

                metrics.actions_total += performed
                metrics.frontier_size = len(frontier)
                metrics.push_window(performed, new_links, plan.stop.soft.plateau_window)

                # soft stop (plateau)
                if len(metrics.window_actions) >= plan.stop.soft.plateau_window:
                    if metrics.frontier_new_ratio < plan.stop.soft.min_new_ratio:
                        logger.info("Soft stop: frontier_new_ratio %.3f < %.3f",
                                    metrics.frontier_new_ratio, plan.stop.soft.min_new_ratio)
                        break

        finally:
            await context.close()
            await browser.close()

    state = WalkState(visited=list(visited), frontier=list(frontier), metrics=metrics)
    return state, snapshots
