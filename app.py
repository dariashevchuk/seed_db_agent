import asyncio
import logging
import typer

from rag_agent.logging_setup import setup_logging
from rag_agent.models import StopConfig
from rag_agent.fetch import navigate_with_plan
from rag_agent.storage import ORG_PATH, PROJ_PATH

setup_logging()
logger = logging.getLogger("app.cli")

app = typer.Typer(help="Seed DB Agent CLI")


@app.command()
def run(url: str):
    """
    Example:
      python app.py "https://savelife.in.ua/"
    """
    stop = StopConfig()  # use defaults or tune via env in the future

    async def _run():
        state, snaps = await navigate_with_plan(url, stop=stop)
        typer.echo(f"Visited={len(state.visited)} Frontier={len(state.frontier)} "
                   f"Actions={state.metrics.actions_total} NewRatio={state.metrics.frontier_new_ratio:.2f}")
        typer.echo(f"Saved to: orgs={ORG_PATH} projects={PROJ_PATH}")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
