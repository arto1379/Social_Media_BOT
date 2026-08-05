#!/usr/bin/env python3
"""
Development entry point.

    python run.py

Starts Flask's built-in server with the reloader, and - unlike the production
setup - runs the background scheduler in the same process, so a single command
gives you the whole system on a laptop.

It is single-threaded and not hardened, so it is for a laptop or a test box
only. On a real server use gunicorn (Ubuntu) or waitress (Windows) plus the
separate worker process, both covered in CONFIGURE.md.
"""

from __future__ import annotations

import os

# APP_ENV in .env decides which configuration class is used; default to
# development here so "python run.py" never trips the production secret checks.
os.environ.setdefault("APP_ENV", "development")

from app import SKIP_SCHEDULER_ENV, create_app  # noqa: E402  (import after env)
from app.config import get_config  # noqa: E402

# The reloader is on whenever debug is. It runs this module twice: once in the
# supervising parent and again in the child that actually serves requests.
# Only the child may own the scheduler, or every background job would run
# twice - so the parent marks itself out before the application is built.
USE_RELOADER = get_config().DEBUG
if USE_RELOADER and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    os.environ[SKIP_SCHEDULER_ENV] = "1"
else:
    os.environ.pop(SKIP_SCHEDULER_ENV, None)

app = create_app()


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))

    print(f"\n  {app.config['APP_NAME']} - development server")
    print(f"  http://{host}:{port}\n")
    print("  This server is for development only. See CONFIGURE.md for how to")
    print("  run it properly on Ubuntu or Windows.\n")

    app.run(host=host, port=port, debug=USE_RELOADER, use_reloader=USE_RELOADER)
