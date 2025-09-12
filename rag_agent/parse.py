import re, json
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse, urlunparse
from extruct import extract
from w3lib.html import get_base_url
import trafilatura
from readability import Document
from markdownify import markdownify as _md

EMAIL_RE = re.compile(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', re.I)

# ---------- utils ----------
def _canonical_site(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or parsed.path
        if not netloc:
            return None
        host = netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return urlunparse((scheme, host, "", "", "", ""))
    except Exception:
        return None

def _first(d: Optional[Dict[str, Any]], keys: List[str]) -> Optional[str]:
    if not d:
        return None
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return None

def _readable_text(html: str, url: Optional[str] = None) -> str:
    try:
        return trafilatura.extract(html, url=url) or ""
    except Exception:
        return ""

def _jsonld_objects(html: str, url: str) -> List[Dict[str, Any]]:
    base = get_base_url(html, url)
    try:
        data = extract(html, base_url=base, syntaxes=["json-ld"]).get("json-ld", [])
    except Exception:
        data = []
    out: List[Dict[str, Any]] = []
    for raw in data:
        try:
            obj = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(obj, list):
                out.extend([x for x in obj if isinstance(x, dict)])
            elif isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out

# ---------- HTML → Markdown ----------
def main_content_html(html: str) -> str:
    try:
        return Document(html).summary(html_partial=True)
    except Exception:
        return html

def html_to_markdown(html: str) -> str:
    article_html = main_content_html(html)
    return _md(
        article_html,
        heading_style="ATX",
        strip=["script", "style"],
        autolinks=True,
        bullets="*",
    ).strip()

# ---------- signal extractors ----------
def org_signals(fetch: Dict[str, Any]) -> Dict[str, Any]:
    html = fetch.get("html") or ""
    url = fetch.get("url") or ""
    meta = fetch.get("metas") or {}
    title = (fetch.get("title") or "").strip()
    h1 = (fetch.get("h1") or "").strip()

    readable = _readable_text(html, url)
    jsonld = _jsonld_objects(html, url)

    ld_org = None
    for obj in jsonld:
        typ = obj.get("@type")
        types = [t.lower() for t in (typ if isinstance(typ, list) else [typ]) if t]
        if any(t in ("organization", "ngo", "corporation", "localbusiness") for t in types):
            ld_org = obj
            break

    name = None
    website = None
    email = None
    if ld_org:
        name = ld_org.get("name") or ld_org.get("legalName")
        website = ld_org.get("url")
        email = ld_org.get("email")
        cp = ld_org.get("contactPoint")
        if not email and isinstance(cp, dict):
            email = cp.get("email")

    # **Better priority**: h1 → title → og:site_name → twitter:title
    if not name:
        name = h1 or title or _first(meta, ["og:site_name"]) or _first(meta, ["twitter:title"])

    if not website:
        website = _canonical_site(url)

    if not email:
        m = EMAIL_RE.search(readable)
        email = m.group(0) if m else None

    meta_desc = _first(meta, ["description", "og:description", "twitter:description"])
    desc = meta_desc or (readable[:600] if readable else None)

    return {
        "name": (name or "").strip(),
        "website": website,
        "contact_email": email,
        "description": (desc or None),
    }

def project_signals(fetch: Dict[str, Any]) -> Dict[str, Any]:
    html = fetch.get("html") or ""
    url = fetch.get("url") or ""
    meta = fetch.get("metas") or {}
    title = (fetch.get("title") or "").strip()
    h1 = (fetch.get("h1") or "").strip()

    readable = _readable_text(html, url)
    jsonld = _jsonld_objects(html, url)

    ld_proj = None
    org_name = None
    org_site = None

    for obj in jsonld:
        typ = obj.get("@type")
        types = [t.lower() for t in (typ if isinstance(typ, list) else [typ]) if t]
        if any(t in ("project", "creativework", "product", "dataset", "softwareapplication") for t in types):
            ld_proj = obj
        pub = obj.get("publisher") or obj.get("creator") or obj.get("author")
        if isinstance(pub, dict):
            org_name = org_name or pub.get("name")
            org_site = org_site or pub.get("url")

    name = None
    desc = None
    if ld_proj:
        name = ld_proj.get("name") or ld_proj.get("headline") or ld_proj.get("title")
        desc = ld_proj.get("description") or ld_proj.get("abstract")

    if not name:
        name = h1 or _first(meta, ["og:title", "twitter:title"]) or title
    if not desc:
        desc = _first(meta, ["description", "og:description", "twitter:description"]) or (readable[:600] if readable else None)

    if not org_name:
        org_name = _first(meta, ["og:site_name"])
    if not org_site:
        org_site = _canonical_site(url)

    return {
        "name": (name or "").strip(),
        "description": (desc or None),
        "organization_name": org_name,
        "organization_website": org_site,
    }
