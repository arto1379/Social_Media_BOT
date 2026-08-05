"""
The permission catalogue.

The PRD requires that the administrator can give each user access to different
parts of the website. Permissions are modelled as single bits stored in one
integer column on the Role table, which makes checks a cheap bitwise AND and
keeps the schema simple.

Adding a new permission = add one constant below and one entry in ``ALL``.
Never renumber an existing bit: the numbers are persisted in the database.
"""

from __future__ import annotations

from dataclasses import dataclass


class Permission:
    """Individual capability bits. Values are powers of two and are permanent."""

    VIEW_DASHBOARD = 1 << 0     # See the home dashboard and summary numbers
    VIEW_STATISTICS = 1 << 1    # See view/like/revenue statistics pages
    VIEW_VIDEOS = 1 << 2        # Browse the video library
    MANAGE_VIDEOS = 1 << 3      # Add/edit/delete videos and queue uploads
    PUBLISH_VIDEOS = 1 << 4     # Approve a video for actual publishing
    MANAGE_ACCOUNTS = 1 << 5    # Connect/disconnect platform accounts + tokens
    VIEW_TRENDS = 1 << 6        # See researched trends
    MANAGE_TRENDS = 1 << 7      # Trigger research, plan/reject trends
    MANAGE_SETTINGS = 1 << 8    # Change automation and policy settings
    MANAGE_USERS = 1 << 9       # Create users/roles, reset passwords
    VIEW_AUDIT_LOG = 1 << 10    # Read the audit trail
    RUN_JOBS = 1 << 11          # Manually trigger background jobs


@dataclass(frozen=True)
class PermissionInfo:
    """UI metadata for one permission bit (used to render the role editor)."""

    bit: int
    key: str        # stable identifier, e.g. "manage_videos"
    label: str      # short human label
    group: str      # section heading in the role editor
    description: str


# Ordered catalogue - the role editor renders this list verbatim.
ALL: tuple[PermissionInfo, ...] = (
    PermissionInfo(Permission.VIEW_DASHBOARD, "view_dashboard", "View dashboard",
                   "General", "Open the home page and see summary counters."),
    PermissionInfo(Permission.VIEW_STATISTICS, "view_statistics", "View statistics",
                   "General", "See view counts and performance across platforms."),
    PermissionInfo(Permission.VIEW_AUDIT_LOG, "view_audit_log", "View audit log",
                   "General", "Read the record of who changed what and when."),

    PermissionInfo(Permission.VIEW_VIDEOS, "view_videos", "View video library",
                   "Content", "Browse videos and their upload history."),
    PermissionInfo(Permission.MANAGE_VIDEOS, "manage_videos", "Manage videos",
                   "Content", "Upload files, edit metadata, delete and queue videos."),
    PermissionInfo(Permission.PUBLISH_VIDEOS, "publish_videos", "Approve publishing",
                   "Content", "Approve a video so the bot may publish it live."),

    PermissionInfo(Permission.VIEW_TRENDS, "view_trends", "View trends",
                   "Research", "See the trending topics the bot has researched."),
    PermissionInfo(Permission.MANAGE_TRENDS, "manage_trends", "Manage trends",
                   "Research", "Run trend research and plan or reject topics."),

    PermissionInfo(Permission.MANAGE_ACCOUNTS, "manage_accounts", "Manage accounts",
                   "Administration", "Connect platform accounts and handle API tokens."),
    PermissionInfo(Permission.MANAGE_SETTINGS, "manage_settings", "Manage settings",
                   "Administration", "Change automation schedules and content policy."),
    PermissionInfo(Permission.RUN_JOBS, "run_jobs", "Run background jobs",
                   "Administration", "Trigger uploads, stats collection and research by hand."),
    PermissionInfo(Permission.MANAGE_USERS, "manage_users", "Manage users and roles",
                   "Administration", "Create users, assign roles and reset passwords."),
)

# Lookup helpers -------------------------------------------------------------
BY_KEY: dict[str, PermissionInfo] = {info.key: info for info in ALL}
BY_BIT: dict[int, PermissionInfo] = {info.bit: info for info in ALL}

# Every bit OR-ed together - what an administrator implicitly holds.
EVERYTHING: int = 0
for _info in ALL:
    EVERYTHING |= _info.bit


def bits_from_keys(keys) -> int:
    """Turn an iterable of permission keys (from a form) into a bitmask."""
    mask = 0
    for key in keys or ():
        info = BY_KEY.get(str(key).strip())
        if info:
            mask |= info.bit
    return mask


def keys_from_bits(mask: int) -> list[str]:
    """Inverse of :func:`bits_from_keys` - used to pre-check form boxes."""
    return [info.key for info in ALL if mask & info.bit]


def describe(mask: int) -> list[str]:
    """Human-readable labels for a bitmask, for display in tables."""
    return [info.label for info in ALL if mask & info.bit]


def grouped() -> dict[str, list[PermissionInfo]]:
    """Permissions grouped by section, preserving catalogue order."""
    groups: dict[str, list[PermissionInfo]] = {}
    for info in ALL:
        groups.setdefault(info.group, []).append(info)
    return groups


# ---------------------------------------------------------------------------
# Default roles created by "flask seed-roles" on a fresh install.
# name -> (description, permission bitmask)
# ---------------------------------------------------------------------------
DEFAULT_ROLES: dict[str, tuple[str, int]] = {
    "Administrator": (
        "Full access to every part of the site.",
        EVERYTHING,
    ),
    "Editor": (
        "Manages the video library and publishing, but not users or tokens.",
        Permission.VIEW_DASHBOARD
        | Permission.VIEW_STATISTICS
        | Permission.VIEW_VIDEOS
        | Permission.MANAGE_VIDEOS
        | Permission.PUBLISH_VIDEOS
        | Permission.VIEW_TRENDS
        | Permission.MANAGE_TRENDS
        | Permission.RUN_JOBS,
    ),
    "Analyst": (
        "Read-only access to dashboards, statistics and trends.",
        Permission.VIEW_DASHBOARD
        | Permission.VIEW_STATISTICS
        | Permission.VIEW_VIDEOS
        | Permission.VIEW_TRENDS,
    ),
}
