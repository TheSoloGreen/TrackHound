"""Authentication API endpoints with Plex OAuth."""

from datetime import datetime, timedelta
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError, jwt
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database import get_db
from app.models.entities import User
from app.models.schemas import PlexPinResponse, TokenResponse, UserResponse

router = APIRouter()
settings = get_settings()
security = HTTPBearer()

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


def create_access_token(user_id: int) -> str:
    """Create JWT access token."""
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode = {"sub": str(user_id), "exp": expire}
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


async def get_current_user(
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

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

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
        pin_id = pin_data["id"]
        pin_code = pin_data["code"]

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

        if not auth_token:
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
        plex_user_id = str(plex_user["id"])
        plex_username = plex_user.get("username", plex_user.get("title", "Unknown"))
        plex_email = plex_user.get("email")
        plex_thumb = plex_user.get("thumb")

        # Find or create user
        result = await db.execute(
            select(User).where(User.plex_user_id == plex_user_id)
        )
        user = result.scalar_one_or_none()

        if user:
            # Update existing user
            user.plex_username = plex_username
            user.plex_email = plex_email
            user.plex_token = auth_token
            user.plex_thumb_url = plex_thumb
            user.last_login = datetime.utcnow()
        else:
            # Create new user
            user = User(
                plex_user_id=plex_user_id,
                plex_username=plex_username,
                plex_email=plex_email,
                plex_token=auth_token,
                plex_thumb_url=plex_thumb,
            )
            db.add(user)

        await db.flush()

        # Create JWT token
        access_token = create_access_token(user.id)

        return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Get current authenticated user info."""
    return current_user


@router.post("/logout")
async def logout():
    """
    Logout endpoint.
    Client should discard the JWT token.
    """
    return {"message": "Successfully logged out"}
