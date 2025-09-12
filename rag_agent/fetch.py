from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import pathlib
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

logger = logging.getLogger("app.fetch")

ARTIFACTS = pathlib.Path("artifacts")
ARTIFACTS.mkdir(exist_ok=True)

# ---------------- Config (env-tunable) ----------------
SCROLL_STEPS = int(os.getenv("SCROLL_STEPS", "10"))
SCROLL_SLEEP_MS = int(os.getenv("SCROLL_SLEEP_MS", "350"))
EXPAND_CLICKS_LIMIT = int(os.getenv("EXPAND_CLICKS_LIMIT", "20"))
CLICK_TIMEOUT = int(os.getenv("CLICK_TIMEOUT_MS", "1800"))
NAV_TIMEOUT = int(os.getenv("NAV_TIMEOUT_MS", "35000"))

# ---------------- Language-aware patterns ----------------
COOKIE_PATTERNS = [
    r"accept(?: all)? cookies?", r"i agree", r"got it", r"allow all",
    r"akceptuj", r"zgadzam", r"zgadzam się", r"akceptuję",
    r"прийняти", r"погоджуюсь", r"погодитися", r"дозволити",
]
EXPAND_PATTERNS = [
    r"(?:read|show|see|view|load)\s+more", r"more",
    r"expand", r"open", r"details", r"show all",
    r"czytaj więcej", r"więcej", r"rozwiń", r"pokaż więcej",
    r"читати далі", r"більше", r"показати ще", r"детальніше",
]
NAV_TAB_PATTERNS = [
    r"projects?", r"initiatives?", r"programs?", r"our work", r"what we do",
    r"areas of work", r"directions", r"programmes?",
    r"projekty", r"inicjatywy", r"programy", r"działania",
    r"наші (?:проєкти|проекти)", r"ініціативи", r"програми",
]
POPUP_CLOSE_PATTERNS = [
    r"close", r"dismiss", r"hide", r"got it", r"ok", r"accept",
    r"zamknij", r"закрити", r"закрыть", r"schlie(?:s|ß)en", r"fermer", r"chiudi", r"cerrar", r"sluiten",
    r"[×✕✖]",
]

CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

# ---------------- Helpers ----------------
def _sha256(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()

def _safe_re(regex: str) -> re.Pattern:
    return re.compile(regex, flags=re.I)

def _extract_metas(html: str) -> Dict[str, str]:
    metas: Dict[str, str] = {}
    for m in re.finditer(r'<meta\s+([^>]+)>', html, flags=re.I):
        attrs = m.group(1)
        name = None
        content = None
        n = re.search(r'(?:name|property)\s*=\s*["\']([^"\']+)["\']', attrs, flags=re.I)
        c = re.search(r'content\s*=\s*["\']([^"\']*)["\']', attrs, flags=re.I)
        if n:
            name = n.group(1).strip()
        if c:
            content = c.group(1).strip()
        if name and content is not None:
            metas[name] = content
    return metas

def _extract_h1(html: str) -> str:
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, flags=re.I | re.S)
    if not m:
        return ""
    txt = re.sub("<[^>]+>", "", m.group(1))
    return re.sub(r"\s+", " ", txt).strip()

def _collect_jsonld_raw(html: str) -> List[str]:
    out: List[str] = []
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.I | re.S,
    ):
        out.append(m.group(1).strip())
    return out

async def _click_candidates(page, patterns: List[str], limit: int = 10) -> int:
    total = 0
    for pat in patterns:
        if total >= limit:
            break
        regex = _safe_re(pat)
        locators = [
            page.get_by_role("tab", name=regex),
            page.get_by_role("button", name=regex),
            page.get_by_role("link", name=regex),
            page.get_by_text(regex),
        ]
        for loc in locators:
            try:
                count = await loc.count()
                for i in range(min(count, max(0, limit - total))):
                    await loc.nth(i).click(timeout=CLICK_TIMEOUT)
                    await page.wait_for_timeout(200)
                    total += 1
                    if total >= limit:
                        break
            except PWTimeout:
                continue
            except Exception:
                continue
            if total >= limit:
                break
    return total

async def _expand_details(page) -> int:
    try:
        opened = await page.evaluate(
            '(() => { let n = 0; document.querySelectorAll("details").forEach(d => { if (!d.open) { d.open = true; n++; } }); return n; })();'
        )
        return int(opened or 0)
    except Exception:
        return 0

async def _accept_cookies(page) -> int:
    return await _click_candidates(page, COOKIE_PATTERNS, limit=2)

async def _infinite_scroll(page, steps: int = SCROLL_STEPS, sleep_ms: int = SCROLL_SLEEP_MS) -> int:
    done = 0
    for _ in range(max(0, steps)):
        try:
            await page.evaluate("window.scrollBy(0, document.body.scrollHeight);")
            await page.wait_for_timeout(sleep_ms)
            done += 1
        except Exception:
            break
    return done

# ---------- Deep-walk helpers ----------
async def _click_while_appears(page, patterns, max_rounds: int = 8, per_round: int = 10) -> int:
    total = 0
    last_len = await page.evaluate("document.body.innerHTML.length")
    for _ in range(max_rounds):
        clicked = await _click_candidates(page, patterns, limit=per_round)
        if not clicked:
            break
        total += clicked
        await page.wait_for_timeout(500)
        curr_len = await page.evaluate("document.body.innerHTML.length")
        if curr_len <= last_len:
            break
        last_len = curr_len
    return total

async def _open_all_aria_expanders(page, limit: int = 50) -> int:
    js = """
    () => {
      let n = 0;
      const clickable = [];
      const sel = [
        '[aria-expanded="false"]',
        '[data-accordion] button',
        '.accordion button,.accordion__button,.faq__question button,.faq button'
      ].join(',');
      document.querySelectorAll(sel).forEach(el => {
        if (el instanceof HTMLElement) clickable.push(el);
      });
      for (const el of clickable.slice(0, LIMIT)) {
        if (el.getAttribute('aria-expanded') === 'false' || el.matches('.accordion button,.accordion__button,.faq__question button,.faq button')) {
          el.click();
          n++;
        }
      }
      return n;
    }
    """.replace("LIMIT", str(limit))
    try:
        opened = await page.evaluate(js)
        await page.wait_for_timeout(300)
        return int(opened or 0)
    except Exception:
        return 0

async def _scroll_all_overflows(page, per_container_steps: int = 5, max_containers: int = 40) -> int:
    js = """
    async (steps, maxc) => {
      const isScrollable = (el) => {
        const s = getComputedStyle(el);
        return (/(auto|scroll)/).test(s.overflowY || '') && el.scrollHeight > el.clientHeight;
      };
      const els = Array.from(document.querySelectorAll('*')).filter(isScrollable).slice(0, maxc);
      let total = 0;
      for (const el of els) {
        for (let i = 0; i < steps; i++) {
          el.scrollTop = el.scrollHeight;
          total++;
          await new Promise(r => setTimeout(r, 150));
        }
      }
      return total;
    }
    """
    try:
        return int(await page.evaluate(js, per_container_steps, max_containers) or 0)
    except Exception:
        return 0

async def _walk_carousels(page, max_clicks_per: int = 20) -> int:
    js = """
    async (maxClicks) => {
      const selectors = ['.slick-next', '.swiper-button-next', '.owl-next', '[aria-label="Next slide"]', '[data-slide="next"]'];
      const nexts = selectors.flatMap(sel => Array.from(document.querySelectorAll(sel)));
      let clicks = 0;
      for (const nxt of nexts) {
        let c = 0;
        while (c < maxClicks) {
          if (!(nxt instanceof HTMLElement)) break;
          nxt.click();
          clicks++; c++;
          await new Promise(r => setTimeout(r, 150));
        }
      }
      return clicks;
    }
    """
    try:
        return int(await page.evaluate(js, max_clicks_per) or 0)
    except Exception:
        return 0

LANG_PREFS = ["uk", "uk-UA", "ua", "ukrainian", "українська", "українською"]

async def _switch_language(page) -> bool:
    for code in LANG_PREFS:
        loc = page.locator(f'a[hreflang="{code}"]')
        if await loc.count():
            try:
                await loc.first.click()
                await page.wait_for_load_state("domcontentloaded")
                return True
            except Exception:
                pass
    for code in ["Українська", "UA", "Uk", "Ukrainian"]:
        loc = page.get_by_role("link", name=re.compile(rf"^\s*{code}\s*$", re.I))
        if await loc.count():
            try:
                await loc.first.click()
                await page.wait_for_load_state("domcontentloaded")
                return True
            except Exception:
                pass
    return False

async def _walk_iframes(page, per_frame_steps: int = 6) -> int:
    count = 0
    for fr in page.frames:
        if fr is page.main_frame:
            continue
        try:
            await fr.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            await asyncio.sleep(0.2)
            try:
                for txt in ["more", "show more", "see more", "показати ще", "детальніше", "więcej"]:
                    loc = fr.get_by_text(re.compile(txt, re.I))
                    if await loc.count():
                        await loc.first.click()
                        await asyncio.sleep(0.2)
                        count += 1
            except Exception:
                pass
        except Exception:
            continue
    return count

async def _wire_json_capture(context, host_tag: str):
    out_path = ARTIFACTS / f"api-{host_tag}-{int(time.time())}.jsonl"
    out_file = open(out_path, "a", encoding="utf-8")

    async def on_response(resp):
        try:
            ctype = resp.headers.get("content-type", "")
            if "application/json" not in ctype:
                return
            url = resp.url
            if any(k in url for k in ["api", "graphql", "project", "initiative", "program", "posts"]):
                j = await resp.json()
                row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "url": url, "status": resp.status, "json": j}
                print(json.dumps(row, ensure_ascii=False), file=out_file)
        except Exception:
            pass

    context.on("response", on_response)
    return out_file

async def _dom_len(page) -> int:
    try:
        return int(await page.evaluate("document.body.innerText.length"))
    except Exception:
        return 0

# ---------- Popup/overlay/window handling ----------
async def _close_popups(page, loops: int = 3, per_loop: int = 8) -> int:
    total = 0
    close_selectors = [
        '[aria-label*="close" i]', '[aria-label*="dismiss" i]', '[aria-label*="hide" i]',
        'button[title*="close" i]', 'button[title*="dismiss" i]',
        '[data-dismiss="modal"]', '.modal [data-dismiss="modal"]',
        '.mfp-close', '.modal .close', '.modal-close', '.popup-close', '.pswp__button--close',
        '.fancybox-close', '.fancybox__button--close', '.swal2-close', '.lightbox .close',
        '.btn-close', '.close-button', '.Dialog-close', '.dialog__close', '.overlay__close'
    ]
    for _ in range(max(1, loops)):
        for sel in close_selectors:
            try:
                loc = page.locator(sel)
                count = await loc.count()
                for i in range(min(count, per_loop)):
                    try:
                        await loc.nth(i).click(timeout=CLICK_TIMEOUT)
                        await page.wait_for_timeout(150)
                        total += 1
                    except Exception:
                        continue
            except Exception:
                continue
        total += await _click_candidates(page, POPUP_CLOSE_PATTERNS, limit=per_loop)
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(150)
        except Exception:
            pass
    return total

async def _remove_overlay_backdrops(page, max_nodes: int = 8) -> int:
    js = """
    (maxn) => {
      const sels = [
        '.modal-backdrop', '.fancybox-container', '.swal2-container',
        '.lightbox-container', '.ReactModal__Overlay', '[role="dialog"] + .backdrop',
        '[class*="overlay"]', '[class*="backdrop"]'
      ];
      let n = 0;
      const all = [];
      for (const sel of sels) all.push(...document.querySelectorAll(sel));
      for (const el of all.slice(0, maxn)) {
        if (el && el.parentElement) { el.parentElement.removeChild(el); n++; }
      }
      return n;
    }
    """
    try:
        removed = await page.evaluate(js, max_nodes)
        await page.wait_for_timeout(100)
        return int(removed or 0)
    except Exception:
        return 0

def _wire_popup_window_autoclose(context, main_page=None):
    """
    Auto-close only true popups (pages with an opener). Ignore the main page
    and any pages created without an opener (e.g., context.new_page()).
    """
    counter = {"closed_pages": 0}

    async def close_page(pg):
        try:
            await asyncio.sleep(0.05)
            await pg.close()
            counter["closed_pages"] += 1
        except Exception:
            pass

    def on_new_page(pg):
        try:
            # Ignore the main page itself
            if main_page is not None and pg == main_page:
                return
            # Close only if it's a real popup with an opener
            opener = getattr(pg, "opener", None)
            if opener is None:
                return
        except Exception:
            return
        asyncio.create_task(close_page(pg))

    context.on("page", on_new_page)
    return counter

# ---------------- Public API ----------------
async def fetch_page(url: str) -> Dict[str, Any]:
    """
    Navigate to the URL, reveal as much content as possible:
    - Switch language, accept cookies
    - Close popups/overlays (with 'X')
    - Click tabs/accordions, expand 'more' repeatedly
    - Scroll in-page & inside overflow containers
    - Walk carousels and iframes
    - Capture background JSON (API/GraphQL)
    - Auto-close any new tabs/windows (true popups only)
    """
    t0 = time.time()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=CHROME_UA,
            viewport={"width": 1366, "height": 900},
        )

        async def _route(route, request):
            if request.resource_type in ("media", "font"):
                return await route.abort()
            return await route.continue_()

        await context.route("**/*", _route)

        host = urlparse(url).netloc.replace(":", "_")
        cap_file = await _wire_json_capture(context, host_tag=host)

        # Create the main page FIRST, then wire autoclose so we can ignore it
        page = await context.new_page()
        page.set_default_timeout(NAV_TIMEOUT)
        popup_counter = _wire_popup_window_autoclose(context, main_page=page)

        try:
            await page.goto(url, wait_until="domcontentloaded")
        except Exception:
            try:
                cap_file.close()
            except Exception:
                pass
            await context.close()
            await browser.close()
            raise

        # Cookies + language + close any overlays early
        await _accept_cookies(page)
        _ = await _switch_language(page)
        pop1 = await _close_popups(page, loops=2, per_loop=10)

        baseline = await _dom_len(page)

        # ---- Phase 1: tabs + expanders + scrollables ----
        tab_clicks = await _click_candidates(page, NAV_TAB_PATTERNS, limit=12)
        aria_opened = await _open_all_aria_expanders(page, limit=50)
        details_opened = await _expand_details(page)
        expand_clicks = await _click_while_appears(page, EXPAND_PATTERNS, max_rounds=8, per_round=6)
        ovf1 = await _scroll_all_overflows(page, per_container_steps=4, max_containers=30)
        sc_steps = await _infinite_scroll(page, steps=SCROLL_STEPS, sleep_ms=SCROLL_SLEEP_MS)
        car1 = await _walk_carousels(page, max_clicks_per=15)
        ifr1 = await _walk_iframes(page)
        pop2 = await _close_popups(page, loops=2, per_loop=8)
        if pop2 == 0:
            await _remove_overlay_backdrops(page, max_nodes=6)

        try:
            await page.wait_for_load_state("networkidle")
        except Exception:
            pass

        # ---- Phase 2: if the page grew a lot, try another pass ----
        grew = (await _dom_len(page)) - baseline
        ovf2 = car2 = ifr2 = 0
        if grew > 2000:
            expand_clicks += await _click_while_appears(page, EXPAND_PATTERNS, max_rounds=3, per_round=5)
            ovf2 = await _scroll_all_overflows(page, per_container_steps=4, max_containers=30)
            sc_steps += await _infinite_scroll(page, steps=max(2, SCROLL_STEPS // 2), sleep_ms=SCROLL_SLEEP_MS)
            car2 = await _walk_carousels(page, max_clicks_per=10)
            ifr2 = await _walk_iframes(page)
            tab_clicks += await _click_candidates(page, NAV_TAB_PATTERNS, limit=6)
            pop3 = await _close_popups(page, loops=1, per_loop=6)
            if pop3 == 0:
                await _remove_overlay_backdrops(page, max_nodes=4)
            try:
                await page.wait_for_load_state("networkidle")
            except Exception:
                pass

        # Extract data
        html = await page.content()
        title = await page.title()
        h1 = _extract_h1(html)
        metas = _extract_metas(html)
        jsonld_raw = _collect_jsonld_raw(html)

        # Save screenshot artifact
        png_path = ARTIFACTS / f"{host}-{int(time.time())}.png"
        try:
            await page.screenshot(path=str(png_path), full_page=True)
        except Exception:
            try:
                await page.screenshot(path=str(png_path), full_page=False)
            except Exception:
                pass

        try:
            cap_file.close()
        except Exception:
            pass
        await context.close()
        await browser.close()

    dur = (time.time() - t0) * 1000.0
    logger.info(
        ("Fetched in %.0f ms | html_len=%d | title='%s' | h1='%s' | "
         "details_opened=%d | aria_opened=%d | expand_clicks=%d | tab_clicks=%d | "
         "scroll_steps=%d | overflow_scrolls=%d | car_clicks=%d | iframe_clicks=%d | "
         "popup_clicks=%d | new_tabs_closed=%d"),
        dur,
        len(html or ""),
        (title or "")[:80],
        (h1 or "")[:80],
        details_opened,
        aria_opened,
        expand_clicks,
        tab_clicks,
        sc_steps,
        (ovf1 + ovf2),
        (car1 + car2),
        (ifr1 + ifr2),
        (pop1 + pop2),
        popup_counter.get("closed_pages", 0),
    )

    return {
        "url": url,
        "title": title or "",
        "html": html or "",
        "jsonld_raw": jsonld_raw or [],
        "metas": metas or {},
        "h1": h1 or "",
        "screenshot": str(png_path),
        "hash": _sha256(html or ""),
    }
