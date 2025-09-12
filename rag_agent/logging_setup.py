import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging() -> None:
    """
    Minimal, quiet-by-default logging with optional file output.
    Env:
      LOG_LEVEL=INFO|DEBUG|WARNING (default INFO)
      LOG_TO_FILE=1 to also write data/run.log with rotation
    """
    lvl = os.getenv("LOG_LEVEL", "INFO").upper()
    lvl = getattr(logging, lvl, logging.INFO)

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    logging.basicConfig(level=lvl, format=fmt)

    # Keep Playwright chatty logs down
    for noisy in ("asyncio", "playwright", "httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(max(lvl, logging.WARNING))

    if os.getenv("LOG_TO_FILE") == "1":
        fh = RotatingFileHandler(
            "data/run.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setLevel(lvl)
        fh.setFormatter(logging.Formatter(fmt))
        logging.getLogger().addHandler(fh)
