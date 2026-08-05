"""
Social platform adapters.

Everything platform-specific lives behind the :class:`PlatformAdapter`
interface in ``base.py``. The rest of the application (services, web views,
scheduler) only ever talks to that interface, which is what the PRD means by
"for this version only YouTube, with potential to add other social media":
adding Instagram Reels later is a new sub-package plus one line in
``registry.py``, with no changes to the queue, the statistics or the UI.

Importing this package imports the concrete adapters so they register
themselves.
"""

from app.platforms.base import (  # noqa: F401  (re-exported for convenience)
    AuthStart,
    ChannelMetrics,
    PlatformAdapter,
    PlatformAuthError,
    PlatformError,
    PlatformNotConfigured,
    PlatformRetryableError,
    TrendItem,
    UploadResult,
    VideoMetrics,
)
from app.platforms.registry import (  # noqa: F401
    all_adapters,
    get_adapter,
    register_adapter,
)

# Importing the YouTube package runs its @register_adapter decorator.
from app.platforms import youtube  # noqa: F401,E402  (import order is intentional)

__all__ = [
    "AuthStart",
    "ChannelMetrics",
    "PlatformAdapter",
    "PlatformAuthError",
    "PlatformError",
    "PlatformNotConfigured",
    "PlatformRetryableError",
    "TrendItem",
    "UploadResult",
    "VideoMetrics",
    "all_adapters",
    "get_adapter",
    "register_adapter",
]
