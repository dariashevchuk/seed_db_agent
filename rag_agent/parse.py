from __future__ import annotations
import re, json
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse, urljoin
from extruct import extract
from w3lib.html import get_base_url
import trafilatura
from readability import Document
from markdownify import markdownify as _md

EMAIL_RE = re.compile(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}', re.I)
A_TAG_RE = re.compile(r"<a\s+[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def canonical_host(url: str) -> Optional[str]:
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or None
    except Exception:
        return None


def same_site(u: str, root: str) -> bool:
    cu, cr = canonical_host(u), canonical_host(root)
    return bool(cu and cr and (cu == cr or cu.endswith("." + cr) or cr.endswith("." + cu)))


def normalize_url(base: str, href: str) -> Optional[str]:
    try:
        return urljoin(base, href.strip())
    except Exception:
        return None


def extract_jsonld_objects(html: str, url: str) -> List[Dict[str, Any]]:
    try:
        base = get_base_url(html, url)
        data = extract(html, base_url=base, syntaxes=["json-ld"]).get("json-ld", [])
        # Ensure dicts only
        norm: List[Dict[str, Any]] = []
        for obj in data:
            if isinstance(obj, dict):
                norm.append(obj)
        return norm[:50]
    except Exception:
        return []


def extract_anchors(html: str, base_url: str, limit: int = 200) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for m in A_TAG_RE.finditer(html or ""):
        href = m.group(1).strip()
        text = re.sub(r"\s+", " ", (m.group(2) or "").strip())
        absu = normalize_url(base_url, href)
        if not absu or absu in seen:
            continue
        seen.add(absu)
        out.append({"text": text[:200] if text else None, "href": absu})
        if len(out) >= limit:
            break
    return out


def html_to_markdown(html: str) -> str:
    """Readable markdown: trafilatura -> readability -> markdownify fallback."""
    if not html:
        return ""
    try:
        txt = trafilatura.extract(html, include_comments=False) or ""
        if len(txt.strip()) >= 150:
            return txt.strip()
    except Exception:
        pass

    try:
        d = Document(html)
        content = d.summary(html_partial=True)
        md = _md(content or html)
        return md.strip()
    except Exception:
        try:
            return _md(html).strip()
        except Exception:
            return ""


def bootstrap_site_hints(url: str, html: str) -> Dict[str, Any]:
    """Lightweight hints: title/meta/og, best-guess email."""
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    title = (title_m.group(1) or "").strip() if title_m else None

    def _meta(name: str) -> Optional[str]:
        m = re.search(rf'<meta[^>]+name=["\']{re.escape(name)}["\'][^>]+content=["\'](.*?)["\']', html or "", re.I)
        if m:
            return (m.group(1) or "").strip()
        m = re.search(rf'<meta[^>]+property=["\']{re.escape(name)}["\'][^>]+content=["\'](.*?)["\']', html or "", re.I)
        return (m.group(1) or "").strip() if m else None

    site_name = _meta("og:site_name") or _meta("twitter:site") or canonical_host(url)
    description = _meta("description") or _meta("og:description") or _meta("twitter:description")

    emails = set(e.lower() for e in EMAIL_RE.findall(html or ""))
    best_email = next(iter(emails)) if emails else None

    return {
        "title": title,
        "site_name": site_name,
        "meta_description": description,
        "best_email": best_email,
    }
