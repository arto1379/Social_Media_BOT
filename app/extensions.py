"""
Flask extension singletons.

They are created here without an application so that models, blueprints and
tests can import them freely; ``app/__init__.py`` binds them to the concrete
application inside the factory. This is the standard way to avoid circular
imports in a Flask project of this size.
"""

from __future__ import annotations

from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

# ORM. Every model in app/models inherits from ``db.Model``.
db = SQLAlchemy()

# Alembic wrapper: enables "flask db migrate" / "flask db upgrade".
migrate = Migrate()

# Session-based authentication for the web interface.
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to continue."
login_manager.login_message_category = "warning"
login_manager.session_protection = "strong"  # invalidate on IP/agent change

# Global CSRF protection: every POST/PUT/DELETE form must carry a token.
csrf = CSRFProtect()
