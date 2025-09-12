import asyncio
import logging
import pathlib
import typer

from rag_agent.logging_setup import setup_logging
setup_logging()
logger = logging.getLogger("app.cli")

from rag_agent.models import OrganizationOut, ProjectOut
from rag_agent.storage import (
    load_orgs, load_projects, save_orgs, save_projects,
    upsert_org, now_iso, upsert_project,
    ORG_PATH, PROJ_PATH
)
from rag_agent.fetch import fetch_page
from rag_agent.parse import org_signals, project_signals, html_to_markdown
from rag_agent.llm import expand_to_ua_description

ARTIFACTS = pathlib.Path("artifacts")
ARTIFACTS.mkdir(exist_ok=True)

app = typer.Typer(add_completion=False)

def _write_artifact_md(prefix: str, ident: int, md: str) -> str:
    path = ARTIFACTS / f"{prefix}-{ident}.md"
    path.write_text(md or "", encoding="utf-8")
    return str(path.resolve())

def _write_artifact_html(prefix: str, ident: int, html: str) -> str:
    path = ARTIFACTS / f"{prefix}-{ident}.html"
    path.write_text(html or "", encoding="utf-8")
    return str(path.resolve())

def _llm_or_fallback(md: str, fallback: str, min_chars: int) -> str:
    try:
        return expand_to_ua_description(md, fallback_text=fallback or "", min_chars=min_chars)
    except Exception as e:
        logger.warning("LLM unavailable, using fallback: %s", e)
        base = (md or fallback or "").strip()
        if not base:
            return ""
        if len(base) < min_chars:
            base = (base + "\n\n") * (max(1, min_chars // max(1, len(base))))
        return base[: max(min_chars, len(base))]

@app.command()
def org(url: str, min_chars: int = typer.Option(600, help="Minimum characters for UA description")):
    async def run():
        fetched = await fetch_page(url)
        html = fetched.get("html") or ""
        html_len = len(html)

        sig = org_signals(fetched)
        md = html_to_markdown(html)
        md_len = len(md)
        logger.info("Markdown length: %d (html_len=%d)", md_len, html_len)

        ua_desc = _llm_or_fallback(md, sig.get("description") or "", min_chars=min_chars)
        logger.info("Final UA description length: %d", len(ua_desc or ""))

        orgs = load_orgs()
        rec = upsert_org(
            orgs,
            name=sig["name"],
            website=sig.get("website"),
            description=ua_desc,
            contact_email=sig.get("contact_email"),
        )
        # validate only known fields
        OrganizationOut(**{
            "organization_id": rec["organization_id"],
            "name": rec.get("name", ""),
            "description": rec.get("description"),
            "website": rec.get("website"),
            "contact_email": rec.get("contact_email"),
            "created_at": rec.get("created_at", now_iso()),
        })
        save_orgs(orgs)

        md_path = _write_artifact_md("org", rec["organization_id"], md)
        html_path = _write_artifact_html("org", rec["organization_id"], html)

        typer.echo(
            "Upserted organization #{}: {}  •  md: {}  •  html: {}\n"
            "Saved JSON to: {}".format(
                rec["organization_id"], rec["name"], md_path, html_path, str(ORG_PATH)
            )
        )
    asyncio.run(run())

@app.command()
def project(url: str, min_chars: int = typer.Option(600, help="Minimum characters for UA description")):
    async def run():
        fetched = await fetch_page(url)
        html = fetched.get("html") or ""
        html_len = len(html)

        sig = project_signals(fetched)
        md = html_to_markdown(html)
        md_len = len(md)
        logger.info("Markdown length: %d (html_len=%d)", md_len, html_len)

        ua_desc = _llm_or_fallback(md, sig.get("description") or "", min_chars=min_chars)
        logger.info("Final UA description length: %d", len(ua_desc or ""))

        orgs = load_orgs()
        org_name = sig.get("organization_name") or sig["name"]
        org_site = sig.get("organization_website")
        org_rec = upsert_org(orgs, name=org_name, website=org_site, description=None, contact_email=None)
        OrganizationOut(**{
            "organization_id": org_rec["organization_id"],
            "name": org_rec.get("name", ""),
            "description": org_rec.get("description"),
            "website": org_rec.get("website"),
            "contact_email": org_rec.get("contact_email"),
            "created_at": org_rec.get("created_at", now_iso()),
        })
        save_orgs(orgs)

        projs = load_projects()
        prec = upsert_project(
            projs,
            name=sig["name"],
            description=ua_desc,
            source_url=fetched.get("url"),
            organization_id=org_rec["organization_id"],
        )
        ProjectOut(**{
            "project_id": prec["project_id"],
            "name": prec.get("name", ""),
            "description": prec.get("description"),
            "created_at": prec.get("created_at", now_iso()),
            "organization_id": prec.get("organization_id"),
        })
        save_projects(projs)

        md_path = _write_artifact_md("project", prec["project_id"], md)
        html_path = _write_artifact_html("project", prec["project_id"], html)

        typer.echo(
            "Added project #{} ('{}') linked to org #{}  •  md: {}  •  html: {}\n"
            "Saved JSON to: {}".format(
                prec["project_id"], prec["name"], org_rec["organization_id"],
                md_path, html_path, str(PROJ_PATH)
            )
        )
    asyncio.run(run())

if __name__ == "__main__":
    app()
