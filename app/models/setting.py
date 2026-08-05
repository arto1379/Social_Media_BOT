"""
Runtime settings.

Two kinds of configuration exist in this project and they are kept apart on
purpose:

* **Environment** (.env, app/config.py) - things that belong to the machine:
  secrets, paths, ports. Changing them needs a restart.
* **Settings** (this table) - things that belong to the operation: how often to
  publish, how much of the output must be monetisable, default privacy. They
  are edited in the web interface and take effect on the next job run.

Values are stored as JSON text so a setting can be a number, a string or a
list without schema changes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Setting(db.Model):
    """A single key/value pair edited through the settings page."""

    __tablename__ = "settings"

    key = db.Column(db.String(64), primary_key=True)
    value_json = db.Column(db.Text, nullable=False, default="null")
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    updated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_by = db.relationship("User", foreign_keys=[updated_by_id])

    # ------------------------------------------------------------------
    # Value access
    # ------------------------------------------------------------------
    @property
    def value(self) -> Any:
        """Decoded value; falls back to the raw string if it is not JSON."""
        try:
            return json.loads(self.value_json)
        except (TypeError, ValueError):
            return self.value_json

    @value.setter
    def value(self, new_value: Any) -> None:
        self.value_json = json.dumps(new_value)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Setting {self.key}={self.value_json[:40]}>"
