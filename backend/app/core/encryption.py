"""Helpers for encrypting and decrypting sensitive at-rest values."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_ENCRYPTED_PREFIX = "enc::"


def _derive_key(raw_key: str) -> bytes:
    """Derive a valid Fernet key from configured encryption key material."""
    try:
        decoded = base64.urlsafe_b64decode(raw_key.encode("utf-8"))
        if len(decoded) == 32:
            return raw_key.encode("utf-8")
    except Exception:
        pass

    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _cipher() -> Fernet:
    settings = get_settings()
    return Fernet(_derive_key(settings.encryption_key))


def is_encrypted(value: str | None) -> bool:
    """Return true when value is encrypted by TrackHound token encryption."""
    return bool(value) and value.startswith(_ENCRYPTED_PREFIX)


def encrypt_value(value: str) -> str:
    """Encrypt a plaintext value unless it is already encrypted."""
    if is_encrypted(value):
        return value
    token = _cipher().encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{_ENCRYPTED_PREFIX}{token}"


def decrypt_value(value: str) -> str:
    """Decrypt a TrackHound encrypted value, returning plaintext for legacy values."""
    if not is_encrypted(value):
        return value

    encrypted = value[len(_ENCRYPTED_PREFIX) :]
    try:
        return _cipher().decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt stored value with current ENCRYPTION_KEY") from exc
