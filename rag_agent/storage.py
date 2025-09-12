from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("rag_agent.storage")

# ---------- paths (force project-root /data) ----------
DATA_DIR = Path.cwd() / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ORG_PATH = (DATA_DIR / "organizations.json").resolve()
PROJ_PATH = (DATA_DIR / "projects.json").resolve()

# ---------- helpers ----------
def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _load_json_list(path: Path) -> List[Dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        logger.warning("Failed to load %s: %s", path, e)
        return []

def _save_json_list(path: Path, arr: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Saving %d records to %s", len(arr), str(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(arr, f, ensure_ascii=False, indent=2)

def load_orgs() -> List[Dict]:
    return _load_json_list(ORG_PATH)

def save_orgs(orgs: List[Dict]) -> None:
    _save_json_list(ORG_PATH, orgs)

def load_projects() -> List[Dict]:
    return _load_json_list(PROJ_PATH)

def save_projects(projs: List[Dict]) -> None:
    _save_json_list(PROJ_PATH, projs)

def _canonical_site(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        p = urlparse(url)
        scheme = p.scheme or "https"
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return f"{scheme}://{host}" if host else None
    except Exception:
        return None

# ---------- upserts ----------
def upsert_org(
    orgs: List[Dict],
    name: str,
    website: Optional[str],
    description: Optional[str],
    contact_email: Optional[str],
) -> Dict:
    norm = _canonical_site(website)

    # 1) by normalized website
    if norm:
        for o in orgs:
            if _canonical_site(o.get("website")) == norm:
                if description and len(description) > len(o.get("description") or ""):
                    o["description"] = description
                if contact_email and not o.get("contact_email"):
                    o["contact_email"] = contact_email
                if name and not o.get("name"):
                    o["name"] = name
                return o

    # 2) by name (case-insensitive)
    lname = (name or "").strip().lower()
    if lname:
        for o in orgs:
            if (o.get("name") or "").strip().lower() == lname:
                if description and len(description) > len(o.get("description") or ""):
                    o["description"] = description
                if contact_email and not o.get("contact_email"):
                    o["contact_email"] = contact_email
                if norm and not o.get("website"):
                    o["website"] = norm
                return o

    # 3) create new
    new_id = max([o.get("organization_id", 0) for o in orgs], default=0) + 1
    rec = {
        "organization_id": new_id,
        "name": name.strip() if name else "",
        "website": norm or website,
        "contact_email": contact_email,
        "description": description or "",
        "created_at": now_iso(),
    }
    orgs.append(rec)
    return rec

# Prevent duplicate projects; keep provenance via source_url (not validated by ProjectOut)
def upsert_project(
    projs: List[Dict],
    name: str,
    description: Optional[str],
    source_url: Optional[str],
    organization_id: int,
) -> Dict:
    # 1) by (org, source_url)
    if source_url:
        for p in projs:
            if p.get("organization_id") == organization_id and (p.get("source_url") or "") == source_url:
                if description and len(description) > len(p.get("description") or ""):
                    p["description"] = description
                return p

    # 2) by (org, normalized name)
    lname = (name or "").strip().lower()
    if lname:
        for p in projs:
            if p.get("organization_id") == organization_id and (p.get("name") or "").strip().lower() == lname:
                if description and len(description) > len(p.get("description") or ""):
                    p["description"] = description
                if source_url and not p.get("source_url"):
                    p["source_url"] = source_url
                return p

    # 3) create
    new_id = max([p.get("project_id", 0) for p in projs], default=0) + 1
    rec = {
        "project_id": new_id,
        "name": name.strip() if name else "",
        "description": description or "",
        "created_at": now_iso(),
        "organization_id": organization_id,
        "source_url": source_url,
    }
    projs.append(rec)
    return rec
