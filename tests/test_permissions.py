"""
Access control.

The PRD's requirement is specific: the administrator can give users access to
different parts of the site, and the administrator has every access. These
tests pin both halves down.
"""

from __future__ import annotations

from app.models import Role, User
from app.security import permissions as perms
from app.security.permissions import Permission


def test_permission_bits_are_unique():
    """Two permissions sharing a bit would silently grant each other."""
    bits = [info.bit for info in perms.ALL]
    assert len(bits) == len(set(bits))


def test_everything_covers_every_permission():
    """EVERYTHING must include each individual bit."""
    for info in perms.ALL:
        assert perms.EVERYTHING & info.bit


def test_bits_and_keys_round_trip():
    """A form submission converts to a mask and back without loss."""
    keys = ["view_dashboard", "manage_videos", "manage_users"]
    mask = perms.bits_from_keys(keys)
    assert sorted(perms.keys_from_bits(mask)) == sorted(keys)


def test_unknown_keys_are_ignored():
    """A tampered form must not be able to invent permissions."""
    assert perms.bits_from_keys(["view_dashboard", "definitely_not_real"]) == (
        Permission.VIEW_DASHBOARD
    )


def test_role_permissions_apply_to_user(db):
    """A user inherits their role's permissions."""
    role = Role(name="Uploader", permissions=Permission.MANAGE_VIDEOS)
    db.session.add(role)
    db.session.commit()

    user = User(username="bob", role_id=role.id)
    user.set_password("passphrase-for-bob")
    db.session.add(user)
    db.session.commit()

    assert user.can(Permission.MANAGE_VIDEOS)
    assert not user.can(Permission.MANAGE_USERS)


def test_extra_permissions_add_to_role(db):
    """Individual grants stack on top of the role, they do not replace it."""
    role = Role(name="Viewer", permissions=Permission.VIEW_VIDEOS)
    db.session.add(role)
    db.session.commit()

    user = User(
        username="carol",
        role_id=role.id,
        extra_permissions=Permission.PUBLISH_VIDEOS,
    )
    user.set_password("passphrase-for-carol")
    db.session.add(user)
    db.session.commit()

    assert user.can(Permission.VIEW_VIDEOS)
    assert user.can(Permission.PUBLISH_VIDEOS)


def test_admin_has_every_permission(admin):
    """'Admin should have every access' - including permissions added later."""
    for info in perms.ALL:
        assert admin.can(info.bit), f"admin lacks {info.key}"


def test_admin_flag_beats_a_missing_role(db):
    """An administrator with no role at all still has full access."""
    user = User(username="root", is_admin=True, role_id=None)
    user.set_password("root-passphrase-here")
    db.session.add(user)
    db.session.commit()
    assert user.effective_permissions == perms.EVERYTHING


def test_analyst_cannot_manage(analyst):
    """The read-only role really is read-only."""
    assert analyst.can(Permission.VIEW_STATISTICS)
    assert not analyst.can(Permission.MANAGE_VIDEOS)
    assert not analyst.can(Permission.MANAGE_USERS)
    assert not analyst.can(Permission.MANAGE_ACCOUNTS)


def test_password_is_hashed_not_stored(db):
    """The plain password must never be recoverable from the row."""
    user = User(username="dave")
    user.set_password("a-very-secret-passphrase")
    assert "a-very-secret-passphrase" not in user.password_hash
    assert user.check_password("a-very-secret-passphrase")
    assert not user.check_password("wrong")
