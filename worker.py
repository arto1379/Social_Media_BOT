#!/usr/bin/env python3
"""
Background worker entry point.

    python worker.py

Runs exactly one scheduler: the automatic upload planner, the statistics
collector, the trend research and the nightly maintenance. It serves no HTTP
and must run as a single process - deploy/socialbot-worker.service does that.

Why separate from the web service: gunicorn runs several workers, and if each
of them scheduled uploads the same video would be published several times over.
Splitting them means the web tier can scale while the schedule stays single.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

# The scheduler is the entire point of this process, so force it on regardless
# of what the web service sets.
os.environ["SCHEDULER_ENABLED"] = "1"
os.environ.setdefault("APP_ENV", "production")

from app import create_app  # noqa: E402  (import after the env is set)
from app.services import scheduler_service  # noqa: E402

log = logging.getLogger("worker")

# Set by the signal handlers to break the sleep loop.
_shutdown_requested = False


def _handle_signal(signum, _frame):
    """Ask the main loop to stop on SIGTERM (systemd stop) or SIGINT (Ctrl-C)."""
    global _shutdown_requested
    log.info("Received signal %s; shutting down.", signum)
    _shutdown_requested = True


def main() -> int:
    """Start the scheduler and stay alive until asked to stop."""
    app = create_app()

    with app.app_context():
        scheduler = scheduler_service.start(app)
        if scheduler is None:
            log.error(
                "The scheduler did not start. Check that SCHEDULER_ENABLED is not "
                "forced to 0 in the environment."
            )
            return 1

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        log.info("Worker running. Jobs: %s", [job["name"] for job in scheduler_service.job_status()])

        # APScheduler runs its own threads; this loop only keeps the process
        # alive and gives the signal handlers something to interrupt.
        while not _shutdown_requested:
            time.sleep(1)

        scheduler_service.shutdown()
        log.info("Worker stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
