"""
Encryption of secrets at rest.

OAuth refresh tokens are long-lived credentials that grant upload rights to a
YouTube channel. They must never sit in the database in clear text, so every
token blob is encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using the
ENCRYPTION_KEY from .env before it is stored, and decrypted on the way out.

Losing ENCRYPTION_KEY means every stored token is unrecoverable and each
account has to be reconnected - back it up with the database.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

log = logging.getLogger(__name__)


class EncryptionError(RuntimeError):
    """Raised when a value cannot be encrypted or decrypted."""


def _fernet() -> Fernet:
    """Build a Fernet instance from the configured key (validated on use)."""
    key = (current_app.config.get("ENCRYPTION_KEY") or "").strip()
    if not key:
        raise EncryptionError(
            "ENCRYPTION_KEY is not set. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise EncryptionError(
            "ENCRYPTION_KEY is not a valid Fernet key (expects 44 url-safe "
            "base64 characters)."
        ) from exc


def encrypt_text(plaintext: str) -> str:
    """Encrypt a string, returning url-safe base64 ciphertext."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(ciphertext: str) -> str:
    """Decrypt a string produced by :func:`encrypt_text`."""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionError(
            "Stored secret could not be decrypted. This usually means "
            "ENCRYPTION_KEY changed since the value was saved."
        ) from exc


def encrypt_json(payload: dict[str, Any]) -> str:
    """Serialise a dict to JSON and encrypt it (used for credential blobs)."""
    return encrypt_text(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def decrypt_json(ciphertext: str) -> dict[str, Any]:
    """Decrypt and parse a blob written by :func:`encrypt_json`."""
    data = json.loads(decrypt_text(ciphertext))
    if not isinstance(data, dict):
        raise EncryptionError("Decrypted secret was not a JSON object.")
    return data


def mask_secret(value: str | None, keep: int = 4) -> str:
    """
    Render a secret for display, e.g. "AIza...9fQ2".

    Used everywhere the UI has to acknowledge that a token exists without
    leaking it into a browser page or the audit log.
    """
    if not value:
        return "-"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"
