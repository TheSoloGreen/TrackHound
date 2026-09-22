"""Authentication API endpoints with Plex OAuth."""

import asyncio
import time

from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.encryption import encrypt_value
from app.models.database import get_db
from app.models.entities import User
from app.models.schemas import PlexPinResponse, TokenResponse, UserResponse, PasswordLogin, AccountUpdate
from app.core.local_auth import hash_password, verify_password, DUMMY_HASH

router = APIRouter()
settings = get_settings()
security = HTTPBearer()
_login_windows: dict[str, tuple[float, int]] = {}


async def limit_password_attempts(request: Request):
    """Bound unknown-account hashing too; account lockouts also persist in DB."""
    now = time.monotonic()
    for key, (started, _) in list(_login_windows.items()):
        if now - started >= 60:
            del _login_windows[key]
    key = request.client.host if request.client else "unknown"
    started, count = _login_windows.get(key, (now, 0))
    if count >= 20 or (key not in _login_windows and len(_login_windows) >= 2048):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.", headers={"Retry-After": "60"})
    _login_windows[key] = (started, count + 1)

# Plex API endpoints
PLEX_PINS_URL = "https://plex.tv/api/v2/pins"
PLEX_USER_URL = "https://plex.tv/api/v2/user"


def get_plex_headers() -> dict:
    """Get standard Plex API headers."""
    return {
        "Accept": "application/json",
        "X-Plex-Client-Identifier": settings.plex_client_identifier,
        "X-Plex-Product": settings.plex_product,
        "X-Plex-Version": settings.plex_version,
        "X-Plex-Platform": settings.plex_platform,
        "X-Plex-Device-Name": settings.plex_device_name,
    }


def create_access_token(user_id: int, auth_version: int = 0, method: str = "plex") -> str:
    """Create JWT access token."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode = {"sub": str(user_id), "exp": expire, "ver": auth_version, "method": method}
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def reject_plex_user(plex_user_id: str) -> None:
    """Reject an account while preserving its verified Plex ID for operators."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "This Plex account is not approved for this TrackHound instance. "
            f"Ask the administrator to allow Plex account ID {plex_user_id}."
        ),
    )


def require_configured_plex_user(plex_user_id: str) -> bool:
    """Apply a configured allowlist, returning false when bootstrap policy applies."""
    allowed_ids = settings.allowed_plex_user_ids_set
    if not allowed_ids:
        return False
    if plex_user_id not in allowed_ids:
        reject_plex_user(plex_user_id)
    return True


async def require_session_plex_user(plex_user_id: str, db: AsyncSession) -> None:
    """Authorize a JWT session against the allowlist or sole bootstrap owner."""
    if require_configured_plex_user(plex_user_id):
        return
    user_count = await db.scalar(select(func.count(User.id)).where(User.plex_user_id.is_not(None)))
    if user_count != 1:
        reject_plex_user(plex_user_id)


async def lock_bootstrap_transaction(db: AsyncSession) -> None:
    """Serialize empty-allowlist ownership decisions on supported databases."""
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        if not db.in_transaction():
            await db.connection(execution_options={"sqlite_transaction_mode": "IMMEDIATE"})
    elif dialect == "postgresql":
        await db.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="First-user bootstrap is unavailable for this database backend.",
        )


async def require_login_plex_user(plex_user_id: str, db: AsyncSession) -> None:
    """Authorize login and serialize first-user ownership when no list is set."""
    if require_configured_plex_user(plex_user_id):
        return
    await lock_bootstrap_transaction(db)
    existing_ids = (await db.scalars(select(User.plex_user_id).where(User.plex_user_id.is_not(None)))).all()
    if existing_ids and existing_ids != [plex_user_id]:
        reject_plex_user(plex_user_id)


async def get_authenticated_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Dependency to get current authenticated user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            credentials.credentials, settings.secret_key, algorithms=[settings.algorithm]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        raise credentials_exception
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if payload.get("ver", 0) != user.auth_version:
        raise credentials_exception
    if payload.get("method", "plex") == "plex":
        if not user.plex_user_id:
            raise credentials_exception
        await require_session_plex_user(user.plex_user_id, db)
    elif payload.get("method") != "password" or not user.password_hash:
        raise credentials_exception
    return user


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    user = await get_authenticated_user(credentials, db)
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Change the initial password in Account before using TrackHound.")
    return user


@router.get("/plex/login", response_model=PlexPinResponse)
async def initiate_plex_login():
    """
    Initiate Plex OAuth flow.
    Returns a PIN and auth URL for the user to authorize.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            PLEX_PINS_URL,
            headers=get_plex_headers(),
            data={"strong": "true"},
        )

        if response.status_code != 201:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to create Plex PIN",
            )

        pin_data = response.json()
        pin_id = pin_data.get("id")
        pin_code = pin_data.get("code")

        if not pin_id or not pin_code:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected response from Plex API",
            )

        # Build the auth URL
        auth_url = (
            f"https://app.plex.tv/auth#?"
            f"clientID={settings.plex_client_identifier}&"
            f"code={pin_code}&"
            f"context[device][product]={settings.plex_product}&"
            f"context[device][version]={settings.plex_version}&"
            f"context[device][platform]={settings.plex_platform}&"
            f"context[device][device]={settings.plex_device_name}"
        )

        return PlexPinResponse(
            pin_id=pin_id,
            pin_code=pin_code,
            auth_url=auth_url,
        )


@router.post("/plex/callback", response_model=TokenResponse)
async def complete_plex_login(
    pin_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _complete_plex_login(pin_id, db)


async def _complete_plex_login(pin_id, db, link_user=None):
    """
    Complete Plex OAuth flow.
    Check if PIN has been authorized and create/update user.
    """
    async with httpx.AsyncClient() as client:
        # Check PIN status
        response = await client.get(
            f"{PLEX_PINS_URL}/{pin_id}",
            headers=get_plex_headers(),
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired PIN",
            )

        pin_data = response.json()
        auth_token = pin_data.get("authToken")

        if not auth_token or not auth_token.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PIN not yet authorized. Please complete authorization in browser.",
            )

        # Get user info from Plex
        user_response = await client.get(
            PLEX_USER_URL,
            headers={**get_plex_headers(), "X-Plex-Token": auth_token},
        )

        if user_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to get user info from Plex",
            )

        plex_user = user_response.json()
        plex_user_id = str(plex_user.get("id", ""))
        if not plex_user_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to get user ID from Plex",
            )
        await require_login_plex_user(plex_user_id, db)
        plex_username = plex_user.get("username", plex_user.get("title", "Unknown"))
        plex_email = plex_user.get("email")
        plex_thumb = plex_user.get("thumb")

        # Find or create user
        result = await db.execute(
            select(User).where(User.plex_user_id == plex_user_id)
        )
        user = result.scalar_one_or_none()

        if link_user:
            if user and user.id != link_user.id:
                raise HTTPException(status_code=409, detail="This Plex account already belongs to another TrackHound account.")
            if link_user.plex_user_id and link_user.plex_user_id != plex_user_id:
                raise HTTPException(status_code=409, detail="This account is already linked to a different Plex account.")
            user = link_user
            user.plex_user_id = plex_user_id

        if user:
            # Update existing user
            user.plex_username = plex_username
            user.plex_email = plex_email
            user.plex_token = encrypt_value(auth_token)
            user.plex_thumb_url = plex_thumb
            user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            # Create new user
            user = User(
                plex_user_id=plex_user_id,
                plex_username=plex_username,
                plex_email=plex_email,
                plex_token=encrypt_value(auth_token),
                plex_thumb_url=plex_thumb,
            )
            db.add(user)

        await db.flush()

        # Create JWT token
        access_token = create_access_token(user.id, user.auth_version)

        return TokenResponse(access_token=access_token)


@router.post("/plex/link", response_model=TokenResponse)
async def link_plex(pin_id: int,
                    current_user: Annotated[User, Depends(get_current_user)],
                    db: Annotated[AsyncSession, Depends(get_db)]):
    return await _complete_plex_login(pin_id, db, current_user)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: Annotated[User, Depends(get_authenticated_user)],
):
    """Get current authenticated user info."""
    return current_user


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(limit_password_attempts)])
async def password_login(request: PasswordLogin, db: Annotated[AsyncSession, Depends(get_db)]):
    # Serialize counters across workers; commit failed attempts before raising.
    await lock_bootstrap_transaction(db)
    user = await db.scalar(select(User).where(User.username == request.username.strip().lower()))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    valid = await asyncio.to_thread(verify_password, request.password,
                                    user.password_hash if user and user.password_hash else DUMMY_HASH)
    if user and user.locked_until and user.locked_until > now:
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again in 15 minutes.",
                            headers={"Retry-After": "900"})
    if not user or not user.password_hash or not valid:
        if user:
            if user.locked_until:
                user.failed_login_attempts = 0
                user.locked_until = None
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = now + timedelta(minutes=15)
            await db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = now
    await db.commit()
    return TokenResponse(access_token=create_access_token(user.id, user.auth_version, "password"))


@router.put("/account", response_model=TokenResponse, dependencies=[Depends(limit_password_attempts)])
async def update_account(request: AccountUpdate,
                         current_user: Annotated[User, Depends(get_authenticated_user)],
                         db: Annotated[AsyncSession, Depends(get_db)]):
    if current_user.password_hash and not await asyncio.to_thread(
            verify_password, request.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if (current_user.must_change_password or not current_user.password_hash) and not request.new_password:
        raise HTTPException(status_code=400, detail="Choose a new password of at least 12 characters.")
    if request.new_password and current_user.password_hash and await asyncio.to_thread(
            verify_password, request.new_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Choose a different password.")
    duplicate = await db.scalar(select(User.id).where(User.username == request.username, User.id != current_user.id))
    if duplicate:
        raise HTTPException(status_code=409, detail="That username is already in use.")
    user_id, version = current_user.id, current_user.auth_version
    password_hash = (await asyncio.to_thread(hash_password, request.new_password)
                     if request.new_password else current_user.password_hash)
    # Release the read snapshot, then change credentials only if this session's
    # version still matches. Concurrent rotations must not resurrect old tokens.
    await db.rollback()
    from sqlalchemy.exc import IntegrityError
    try:
        result = await db.execute(update(User).where(User.id == user_id, User.auth_version == version).values(
            username=request.username, password_hash=password_hash, must_change_password=False,
            auth_version=version + 1, failed_login_attempts=0, locked_until=None))
        if result.rowcount != 1:
            raise HTTPException(status_code=401, detail="Account changed. Sign in again.")
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="That username is already in use.")
    return TokenResponse(access_token=create_access_token(user_id, version + 1, "password"))


@router.post("/logout")
async def logout():
    """
    Logout endpoint.
    Client should discard the JWT token.
    """
    return {"message": "Successfully logged out"}
