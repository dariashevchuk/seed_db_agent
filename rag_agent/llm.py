import os
import json
from typing import Any, Dict, List

from openai import OpenAI

from rag_agent.models import Plan, ReflectOutput, Snapshot


def _client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=api_key)


def plan_site_walk(url: str) -> Plan:
    """
    Keep planning simple & deterministic. We can LLM-plan later if needed.
    """
    return Plan(
        start_url=url,
        same_domain_only=True,
        domain_allowlist=[],
        prefer_languages=["uk", "en"],
    )


def _format_snapshots(snapshots: List[Snapshot]) -> str:
    lines: List[str] = []
    for i, s in enumerate(snapshots, 1):
        lines.append(f"# Snapshot {i}")
        lines.append(f"URL: {s.url}")
        if s.title:
            lines.append(f"Title: {s.title}")
        if s.site_name:
            lines.append(f"Site: {s.site_name}")
        if s.meta_description:
            lines.append(f"Meta: {s.meta_description[:300]}")
        if s.jsonld_objects:
            lines.append("JSON-LD: present")
        if s.anchors:
            top = ", ".join((a.text or "")[:50] for a in s.anchors[:8] if (a.text or "").strip())
            if top:
                lines.append(f"Anchors: {top[:300]}")
        if s.markdown:
            lines.append(f"Markdown preview: {s.markdown[:600]}")
        lines.append("")
    return "\n".join(lines)


def _normalize_reflect_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    # coverage normalization
    cov = str(raw.get("coverage", "")).strip().lower()
    cov_map = {
        "full": "sufficient",
        "complete": "sufficient",
        "enough": "sufficient",
        "ok": "sufficient",
        "satisfactory": "sufficient",
    }
    cov = cov_map.get(cov, cov)
    if cov not in {"none", "partial", "sufficient"}:
        cov = "partial"
    raw["coverage"] = cov

    # ensure list-y fields
    raw["goto_urls"] = [u for u in (raw.get("goto_urls") or []) if isinstance(u, str)]
    raw["projects"] = [p for p in (raw.get("projects") or []) if isinstance(p, dict)]
    raw["actions"] = raw.get("actions") or []

    # actions normalization
    norm_actions: List[Dict[str, Any]] = []
    for a in raw["actions"]:
        if not isinstance(a, dict):
            continue
        t = str(a.get("type", "")).strip().upper()
        if t in {"SCROLL_TO_BOTTOM", "SCROLLDOWN", "SCROLL-BOTTOM", "SCROLL_PAGE"}:
            t = "SCROLL"
        elif t in {"OPEN-SITEMAP", "SITEMAP"}:
            t = "OPEN_SITEMAP"
        elif t in {"OPEN-ROBOTS", "ROBOTS"}:
            t = "OPEN_ROBOTS"
        elif t in {"VISIT", "NAVIGATE", "OPEN", "GOTO_URL"}:
            t = "GOTO"
        norm_actions.append({
            "type": t,
            "url": a.get("url"),
            "pattern": a.get("pattern"),
            "arg": a.get("arg"),
        })
    raw["actions"] = norm_actions

    # light cleanup: drop empty projects without names
    raw["projects"] = [p for p in raw["projects"] if (p.get("name") or "").strip()]

    return raw


def reflect_and_extract(plan: Plan, snapshots: List[Snapshot]) -> ReflectOutput:
    """
    Single reflection step: summarize page(s), extract org/project data, propose new URLs and actions.
    Robust to minor schema deviations from the model.
    """
    client = _client()
    header = (
        "You are a precise extractor for Ukrainian non-profits and their projects.\n"
        "- Prefer Ukrainian ('uk') content. English ('en') is acceptable.\n"
        "- Use JSON-LD if present.\n"
        "- Only include projects that clearly belong to the current organization.\n"
        "- Return strict JSON with keys: done, coverage, justification, organization, projects, goto_urls, actions.\n"
        "- coverage MUST be one of: 'none', 'partial', 'sufficient' (use 'sufficient' instead of 'full').\n"
        "- 'goto_urls' must only contain links that likely list more projects of this same organization.\n"
        "- 'projects': each item has name, description, source_url.\n"
        "- 'organization': name, website, contact_email, description.\n"
    )
    user = _format_snapshots(snapshots)

    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": header},
            {"role": "user", "content": user},
        ],
    )
    content = resp.choices[0].message.content or "{}"

    # Parse JSON safely; normalize to our schema; then validate.
    try:
        raw = json.loads(content)
    except Exception:
        # handle accidental code fences or stray text
        text = content.strip().strip("```").strip()
        raw = json.loads(text) if text.startswith("{") else {}

    raw = _normalize_reflect_payload(raw)
    return ReflectOutput.model_validate(raw)


def expand_to_ua_description(short_text: str, site_markdown: str | None = None, min_chars: int = 600) -> str:
    """
    Expand a short project/org blurb into a cohesive Ukrainian paragraph >= min_chars.
    """
    client = _client()
    prompt = (
        "Розшир цю коротку анотацію до змістовного опису українською мовою. "
        f"Мінімум {min_chars} символів, один зв'язний абзац, без рекомендацій і без вигадування фактів."
    )
    given = f"Короткий текст:\n{short_text.strip()}\n\n"
    if site_markdown:
        given += f"Контекст сторінки (витяг):\n{(site_markdown or '')[:1200]}\n"

    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Return JSON: {\"text\": \"...\"}"},
            {"role": "user", "content": prompt + "\n\n" + given},
        ],
    )

    content = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
        text = data.get("text", "").strip()
        return text or short_text
    except Exception:
        return short_text
