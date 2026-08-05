"""
Production WSGI entry point.

Ubuntu (gunicorn), as used by deploy/socialbot.service::

    gunicorn --workers 3 --bind 127.0.0.1:8000 wsgi:application

Windows (waitress)::

    waitress-serve --listen=127.0.0.1:8000 wsgi:application

The scheduler is intentionally NOT started here. With several gunicorn workers
each one would run its own copy and publish the same video several times, so
the web service sets SCHEDULER_ENABLED=0 and a single separate worker process
(worker.py / socialbot-worker.service) owns the schedule.
"""

from __future__ import annotations

import os

from app import create_app

# Production is the default when APP_ENV is unset - an unconfigured server
# should behave strictly rather than loosely.
os.environ.setdefault("APP_ENV", "production")

application = create_app()

# Some tooling looks for "app" rather than "application"; expose both.
app = application
