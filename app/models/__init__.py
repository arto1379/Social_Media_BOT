"""
Database models.

Every table lives in its own module so a change to, say, the upload queue never
forces you to read the user code. This package re-exports them all so callers
can simply write ``from app.models import Video, UploadJob``.

Importing this package registers the models with SQLAlchemy's metadata, which
is what ``db.create_all()`` and Alembic autogeneration rely on.
"""

from app.models.account import PlatformAccount
from app.models.audit import AuditLog
from app.models.setting import Setting
from app.models.stats import StatSnapshot
from app.models.trend import Trend, TrendStatus
from app.models.upload import UploadJob, UploadStatus
from app.models.user import Role, User
from app.models.video import LicenseType, Video, VideoSource, VideoStatus

__all__ = [
    "AuditLog",
    "LicenseType",
    "PlatformAccount",
    "Role",
    "Setting",
    "StatSnapshot",
    "Trend",
    "TrendStatus",
    "UploadJob",
    "UploadStatus",
    "User",
    "Video",
    "VideoSource",
    "VideoStatus",
]
