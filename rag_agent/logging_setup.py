import logging, os

def setup_logging(level: str | None = None) -> None:
    """
    Configure root logging once. Use LOG_LEVEL env (DEBUG, INFO, WARNING, ERROR).
    """
    lvl_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    lvl = getattr(logging, lvl_name, logging.INFO)

    # Idempotent: do nothing if already configured.
    if logging.getLogger().handlers:
        logging.getLogger().setLevel(lvl)
        return

    logging.basicConfig(
        level=lvl,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # Quiet some chatty libs unless we asked for DEBUG.
    if lvl > logging.DEBUG:
        for noisy in ("asyncio", "urllib3", "httpx", "playwright"):
            logging.getLogger(noisy).setLevel(max(lvl, logging.WARNING))
