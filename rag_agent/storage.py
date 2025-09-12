from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from rag_agent.models import OrganizationOut, ProjectOut
from rag_agent.llm import expand_to_ua_description

logger = logging.getLogger("rag_agent.storage")

# ---------- paths ----------
DATA_DIR = Path.cwd() / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ORG_PATH = (DATA_DIR / "organizations.json").resolve()
PROJ_PATH = (DATA_DIR / "projects.json").resolve()


# ---------- utils ----------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json_list(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        logger.warning("File %s did not contain a list, resetting.", path)
        return []
    except Exception as e:
        logger.warning("Failed to load %s: %s", path, e)
        return []


def _atomic_write(path: Path, payload: List[Dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_orgs() -> List[Dict]:
    return _load_json_list(ORG_PATH)


def save_orgs(orgs: List[Dict]) -> None:
    logger.info("Saving %d records to %s", len(orgs), ORG_PATH)
    _atomic_write(ORG_PATH, orgs)


def load_projects() -> List[Dict]:
    return _load_json_list(PROJ_PATH)


def save_projects(projects: List[Dict]) -> None:
    logger.info("Saving %d records to %s", len(projects), PROJ_PATH)
    _atomic_write(PROJ_PATH, projects)


# ---------- upserts ----------
def upsert_org(orgs: List[Dict], payload: OrganizationOut) -> Dict:
    name = (payload.name or "").strip()
    website = (payload.website or "").strip() or None

    # 1) match by website (preferred)
    if website:
        for o in orgs:
            if (o.get("website") or "").strip().lower() == website.lower():
                # update in place (non-destructive)
                o["name"] = name or o.get("name") or ""
                if payload.description:
                    o["description"] = payload.description
                if payload.contact_email:
                    o["contact_email"] = payload.contact_email
                return o

    # 2) match by name (fallback)
    for o in orgs:
        if (o.get("name") or "").strip().lower() == name.lower():
            if payload.website:
                o["website"] = payload.website
            if payload.description:
                o["description"] = payload.description
            if payload.contact_email:
                o["contact_email"] = payload.contact_email
            return o

    # 3) create
    new_id = max([o.get("organization_id", 0) for o in orgs], default=0) + 1
    rec = {
        "organization_id": new_id,
        "name": name,
        "description": payload.description or "",
        "website": payload.website or "",
        "contact_email": payload.contact_email or None,
        "created_at": now_iso(),
    }
    orgs.append(rec)
    return rec


def upsert_project(
    projs: List[Dict],
    *,
    organization_id: int,
    name: str,
    description: str | None,
    source_url: str | None,
    ensure_min_chars: int = 600,
    site_markdown: str | None = None,
) -> Dict:
    nm = (name or "").strip()
    src = (source_url or "").strip()

    # Update existing by (org_id + name) OR by source_url
    for p in projs:
        if src and (p.get("source_url") or "").strip().lower() == src.lower():
            if nm:
                p["name"] = nm
            if description and (len(description) > len(p.get("description") or "")):
                p["description"] = description
            return p

    for p in projs:
        if p.get("organization_id") == organization_id and (p.get("name") or "").strip().lower() == nm.lower():
            if description and (len(description) > len(p.get("description") or "")):
                p["description"] = description
            if src:
                p["source_url"] = src
            return p

    # Expand if too short
    final_desc = (description or "").strip()
    if len(final_desc) < ensure_min_chars and final_desc:
        try:
            final_desc = expand_to_ua_description(final_desc, site_markdown=site_markdown, min_chars=ensure_min_chars)
        except Exception:
            pass

    new_id = max([p.get("project_id", 0) for p in projs], default=0) + 1
    rec = {
        "project_id": new_id,
        "name": nm,
        "description": final_desc,
        "created_at": now_iso(),
        "organization_id": organization_id,
        "source_url": src or None,
    }
    projs.append(rec)
    return rec
