"""
Adapter registry.

Adapters register themselves at import time with the ``@register_adapter``
decorator, so the rest of the app can ask for one by name without importing
platform modules directly::

    from app.platforms import get_adapter
    adapter = get_adapter(account.platform)

Adding a platform therefore never requires editing the services or the views.
"""

from __future__ import annotations

import logging

from app.platforms.base import PlatformAdapter, PlatformError

log = logging.getLogger(__name__)

# name -> singleton adapter instance. Adapters are stateless, so one instance
# per process is enough and keeps discovery cheap.
_REGISTRY: dict[str, PlatformAdapter] = {}


class UnknownPlatform(PlatformError):
    """Raised when a platform key has no registered adapter."""


def register_adapter(cls: type[PlatformAdapter]) -> type[PlatformAdapter]:
    """Class decorator that instantiates and registers an adapter."""
    instance = cls()
    if not instance.name:
        raise ValueError(f"{cls.__name__} must define a 'name' attribute.")
    if instance.name in _REGISTRY:
        log.warning("Platform adapter %r registered twice; keeping the first.", instance.name)
        return cls
    _REGISTRY[instance.name] = instance
    log.debug("Registered platform adapter %r", instance.name)
    return cls


def get_adapter(name: str) -> PlatformAdapter:
    """Return the adapter registered under *name*."""
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise UnknownPlatform(
            f"No adapter is registered for platform {name!r} (known: {known})."
        ) from exc


def all_adapters() -> list[PlatformAdapter]:
    """Every registered adapter, ordered by display name (for menus)."""
    return sorted(_REGISTRY.values(), key=lambda a: a.display_name.lower())


def adapter_names() -> list[str]:
    """Machine keys of every registered adapter."""
    return sorted(_REGISTRY)
