"""Local password hashing and idempotent first-start account setup."""
import asyncio
import hashlib
import hmac
import logging
import os
from pathlib import Path
import secrets

from sqlalchemy import select

from app.config import get_settings
from app.models.database import async_session_maker
from app.models.entities import User

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768,
                            r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
    return f"scrypt${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768,
                                r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


# Equal-cost verification for unknown usernames. Never an account credential.
DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def initial_password(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Reuse after an interrupted bootstrap, never overwrite a supplied file.
        password = path.read_text(encoding="utf-8").strip()
    else:
        password = secrets.token_urlsafe(24)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(password + "\n")
    if not 12 <= len(password) <= 128:
        raise ValueError("Initial admin password file must contain 12–128 characters.")
    return password


async def bootstrap_local_account(session_factory=None, password_file=None):
    # This lock also serializes bootstrap with concurrent Plex sign-ins/workers.
    from app.api.auth import lock_bootstrap_transaction
    async with (session_factory or async_session_maker)() as db:
        await lock_bootstrap_transaction(db)
        users = (await db.scalars(select(User).order_by(User.id))).all()
        if any(user.password_hash for user in users):
            return
        # Preserve the existing single owner's catalog. With multiple Plex users,
        # create an independent local account; never choose another user's data.
        user = users[0] if len(users) == 1 else User(plex_username="admin")
        path = Path(password_file or get_settings().initial_admin_password_file)
        password = await asyncio.to_thread(initial_password, path)
        user.username = "admin"
        user.password_hash = await asyncio.to_thread(hash_password, password)
        user.must_change_password = True
        db.add(user)
        await db.commit()
        logger.info("Initial local login: admin. Read the password from %s; change it at first login.", path)
