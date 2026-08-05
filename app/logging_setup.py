"""
Logging configuration.

Two sinks are configured:

* stdout   - picked up by systemd/journalctl (``journalctl -u socialbot``).
* a file   - ``<LOG_ROOT>/socialbot.log``, rotated at 5 MB, 5 backups kept,
             so a long-running server never fills the disk with logs.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# One line format used by both handlers; includes the module so it is obvious
# which service produced the message (upload, stats, trends, ...).
_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging(app) -> None:
    """Attach stdout + rotating-file handlers to the root logger."""
    log_root: Path = app.config["LOG_ROOT"]
    log_root.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, app.config.get("LOG_LEVEL", "INFO"), logging.INFO)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    root = logging.getLogger()
    root.setLevel(level)

    # Re-running the factory (tests, "flask shell") must not stack handlers.
    for handler in list(root.handlers):
        if getattr(handler, "_socialbot", False):
            root.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler._socialbot = True  # type: ignore[attr-defined]
    root.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        log_root / "socialbot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler._socialbot = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    # Third-party libraries are chatty at INFO; keep them at WARNING so our own
    # messages stay readable in the journal.
    for noisy in ("googleapiclient.discovery_cache", "apscheduler.executors.default", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    app.logger.setLevel(level)
