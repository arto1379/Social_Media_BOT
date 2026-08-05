"""
Platform accounts and API tokens.

The OAuth handshake lives here:

1. ``create`` makes a local account row and sends the browser to the platform.
2. The platform redirects back to ``oauth_callback`` with a code.
3. The code is exchanged for tokens, which are encrypted and stored.

The ``state`` parameter is generated per attempt, kept in the session and
checked on the way back. Without that check anybody could feed the callback URL
a code of their own and attach their channel to this installation.

Tokens are never rendered. The page shows that a token exists, when it expires
and whether the last API call worked - nothing more.
"""

from __future__ import annotations

import logging
import secrets

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.models import PlatformAccount
from app.platforms import (
    PlatformError,
    PlatformNotConfigured,
    all_adapters,
    get_adapter,
)
from app.security.access import Permission, permission_required
from app.services import account_service, audit_service
from app.web.forms import AccountForm, CSRFOnlyForm

log = logging.getLogger(__name__)

bp = Blueprint("accounts", __name__, template_folder="../templates")

# Session keys used to carry state across the OAuth round trip.
SESSION_STATE = "oauth_state"
SESSION_ACCOUNT = "oauth_account_id"


def _redirect_uri(platform: str) -> str:
    """
    The callback URL registered with the platform.

    Built from PUBLIC_BASE_URL rather than from the incoming request so it
    matches the value registered in the Google console exactly - a mismatch is
    the single most common cause of a failed connection.
    """
    base = current_app.config["PUBLIC_BASE_URL"].rstrip("/")
    return f"{base}{url_for('accounts.oauth_callback', platform=platform)}"


@bp.route("/")
@login_required
@permission_required(Permission.MANAGE_ACCOUNTS)
def index():
    """List connected accounts and the state of each platform integration."""
    accounts = db.session.query(PlatformAccount).order_by(PlatformAccount.id).all()
    adapters = [
        {
            "name": adapter.name,
            "display_name": adapter.display_name,
            "configured": adapter.is_configured(),
            "hint": adapter.configuration_hint(),
            "supports_trends": adapter.supports_trends,
            "supports_revenue": adapter.supports_revenue,
            "redirect_uri": _redirect_uri(adapter.name),
        }
        for adapter in all_adapters()
    ]
    return render_template(
        "accounts/index.html",
        accounts=accounts,
        adapters=adapters,
        action_form=CSRFOnlyForm(),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required(Permission.MANAGE_ACCOUNTS)
def create():
    """Create an account record and start the authorisation flow."""
    form = AccountForm()
    form.platform.choices = [
        (adapter.name, adapter.display_name)
        for adapter in all_adapters()
        if adapter.is_configured()
    ]

    if not form.platform.choices:
        flash(
            "No platform is configured yet. Add the API client id and secret to "
            ".env first - the Accounts page lists what each platform needs.",
            "warning",
        )
        return redirect(url_for("accounts.index"))

    if form.validate_on_submit():
        account = PlatformAccount(
            platform=form.platform.data,
            display_name=form.display_name.data.strip(),
            is_default=form.is_default.data,
            created_by_id=current_user.id,
        )
        # Only one default per platform.
        if account.is_default:
            db.session.query(PlatformAccount).filter(
                PlatformAccount.platform == account.platform
            ).update({"is_default": False})
        db.session.add(account)
        db.session.commit()

        audit_service.record(
            "account.create", target_type="account", target_id=account.id,
            detail=f"Created {account.platform} account '{account.display_name}'.",
        )
        return redirect(url_for("accounts.connect", account_id=account.id))

    return render_template("accounts/form.html", form=form)


@bp.route("/<int:account_id>/connect")
@login_required
@permission_required(Permission.MANAGE_ACCOUNTS)
def connect(account_id: int):
    """Send the browser to the platform's consent screen."""
    account = db.session.get(PlatformAccount, account_id) or abort(404)

    try:
        adapter = get_adapter(account.platform)
        state = secrets.token_urlsafe(32)
        auth_start = adapter.start_authorization(_redirect_uri(account.platform), state)
    except PlatformNotConfigured as exc:
        flash(str(exc), "danger")
        return redirect(url_for("accounts.index"))
    except PlatformError as exc:
        log.exception("Could not start authorisation for account %s", account_id)
        flash(f"Authorisation could not be started: {exc}", "danger")
        return redirect(url_for("accounts.index"))

    # Remember what we are authorising, and verify it on the way back.
    session[SESSION_STATE] = auth_start.state
    session[SESSION_ACCOUNT] = account.id
    return redirect(auth_start.authorization_url)


@bp.route("/oauth/callback/<platform>")
@login_required
@permission_required(Permission.MANAGE_ACCOUNTS)
def oauth_callback(platform: str):
    """Handle the redirect back from the platform and store the tokens."""
    expected_state = session.pop(SESSION_STATE, None)
    account_id = session.pop(SESSION_ACCOUNT, None)
    returned_state = request.args.get("state")

    # The user pressed "cancel" on the consent screen.
    if request.args.get("error"):
        flash(f"Authorisation was cancelled: {request.args['error']}", "warning")
        return redirect(url_for("accounts.index"))

    if not expected_state or expected_state != returned_state:
        log.warning("OAuth state mismatch on callback for %s", platform)
        flash(
            "The authorisation could not be verified (state mismatch). Start "
            "again from the Accounts page.",
            "danger",
        )
        return redirect(url_for("accounts.index"))

    account = db.session.get(PlatformAccount, account_id) if account_id else None
    if account is None or account.platform != platform:
        flash("The account being connected no longer exists.", "danger")
        return redirect(url_for("accounts.index"))

    try:
        adapter = get_adapter(platform)
        credentials = adapter.complete_authorization(
            _redirect_uri(platform), request.url, expected_state
        )
        account.set_credentials(credentials)
        account.scopes = " ".join(credentials.get("scopes", []))
        account.token_expires_at = account_service.parse_expiry(credentials.get("expiry"))
        account_service.sync_account_identity(account, credentials)
        account.last_error = None
        db.session.commit()
    except PlatformError as exc:
        db.session.rollback()
        log.exception("Authorisation failed for account %s", account_id)
        flash(f"Authorisation failed: {exc}", "danger")
        return redirect(url_for("accounts.index"))

    audit_service.record(
        "account.connect", target_type="account", target_id=account.id,
        detail=f"Connected {platform} channel '{account.display_name}' "
               f"({account.remote_id}).",
    )
    flash(f"Connected to {account.display_name}.", "success")
    return redirect(url_for("accounts.index"))


@bp.route("/<int:account_id>/test", methods=["POST"])
@login_required
@permission_required(Permission.MANAGE_ACCOUNTS)
def test(account_id: int):
    """Make one API call to check that the stored token still works."""
    account = db.session.get(PlatformAccount, account_id) or abort(404)
    if not CSRFOnlyForm().validate_on_submit():
        abort(400)

    ok, message = account_service.test_connection(account)
    flash(message, "success" if ok else "danger")
    return redirect(url_for("accounts.index"))


@bp.route("/<int:account_id>/toggle", methods=["POST"])
@login_required
@permission_required(Permission.MANAGE_ACCOUNTS)
def toggle(account_id: int):
    """Enable or disable an account without disconnecting it."""
    account = db.session.get(PlatformAccount, account_id) or abort(404)
    if not CSRFOnlyForm().validate_on_submit():
        abort(400)

    account.is_active = not account.is_active
    db.session.commit()
    audit_service.record(
        "account.toggle", target_type="account", target_id=account.id,
        detail=f"{'Enabled' if account.is_active else 'Disabled'} "
               f"'{account.display_name}'.",
    )
    flash(
        f"'{account.display_name}' is now {'enabled' if account.is_active else 'disabled'}.",
        "info",
    )
    return redirect(url_for("accounts.index"))


@bp.route("/<int:account_id>/disconnect", methods=["POST"])
@login_required
@permission_required(Permission.MANAGE_ACCOUNTS)
def disconnect(account_id: int):
    """Forget the stored tokens but keep the account and its history."""
    account = db.session.get(PlatformAccount, account_id) or abort(404)
    if not CSRFOnlyForm().validate_on_submit():
        abort(400)

    account.clear_credentials()
    db.session.commit()
    audit_service.record(
        "account.disconnect", target_type="account", target_id=account.id,
        detail=f"Removed stored tokens for '{account.display_name}'.",
    )
    flash(
        f"Tokens for '{account.display_name}' were deleted. Revoke the app's "
        f"access at the platform too if you no longer use it.",
        "info",
    )
    return redirect(url_for("accounts.index"))


@bp.route("/<int:account_id>/delete", methods=["POST"])
@login_required
@permission_required(Permission.MANAGE_ACCOUNTS)
def delete(account_id: int):
    """Delete an account record entirely."""
    account = db.session.get(PlatformAccount, account_id) or abort(404)
    if not CSRFOnlyForm().validate_on_submit():
        abort(400)

    if account.upload_jobs.count():
        flash(
            "This account has upload history. Disconnect it instead of deleting "
            "it, so the record of what was published stays intact.",
            "warning",
        )
        return redirect(url_for("accounts.index"))

    name = account.display_name
    db.session.delete(account)
    db.session.commit()
    audit_service.record(
        "account.delete", target_type="account", target_id=account_id,
        detail=f"Deleted account '{name}'.",
    )
    flash(f"Account '{name}' was deleted.", "info")
    return redirect(url_for("accounts.index"))
