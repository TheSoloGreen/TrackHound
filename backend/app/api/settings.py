"""Settings API endpoints for user preferences."""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.models.database import get_db
from app.models.entities import User, UserPreference
from app.models.schemas import (
    UserSettingsResponse,
    UserSettingsUpdate,
    AudioPreferences,
    AnimeDetectionSettings,
)

router = APIRouter()

# Default settings
DEFAULT_AUDIO_PREFERENCES = AudioPreferences()
DEFAULT_ANIME_DETECTION = AnimeDetectionSettings()
DEFAULT_FILE_EXTENSIONS = [".mkv", ".mp4", ".avi", ".m4v"]


async def get_user_preference(
    db: AsyncSession, user_id: int, key: str
) -> str | None:
    """Get a user preference value."""
    result = await db.execute(
        select(UserPreference).where(
            UserPreference.user_id == user_id,
            UserPreference.key == key,
        )
    )
    pref = result.scalar_one_or_none()
    return pref.value if pref else None


async def set_user_preference(
    db: AsyncSession, user_id: int, key: str, value: str
) -> None:
    """Set a user preference value."""
    result = await db.execute(
        select(UserPreference).where(
            UserPreference.user_id == user_id,
            UserPreference.key == key,
        )
    )
    pref = result.scalar_one_or_none()

    if pref:
        pref.value = value
    else:
        pref = UserPreference(user_id=user_id, key=key, value=value)
        db.add(pref)


@router.get("", response_model=UserSettingsResponse)
async def get_settings(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get user settings."""
    # Audio preferences
    audio_json = await get_user_preference(db, current_user.id, "audio_preferences")
    if audio_json:
        try:
            audio_prefs = AudioPreferences.model_validate_json(audio_json)
        except ValidationError:
            audio_prefs = DEFAULT_AUDIO_PREFERENCES
    else:
        audio_prefs = DEFAULT_AUDIO_PREFERENCES

    # Anime detection
    anime_json = await get_user_preference(db, current_user.id, "anime_detection")
    if anime_json:
        try:
            anime_detection = AnimeDetectionSettings.model_validate_json(anime_json)
        except ValidationError:
            anime_detection = DEFAULT_ANIME_DETECTION
    else:
        anime_detection = DEFAULT_ANIME_DETECTION

    # File extensions
    ext_json = await get_user_preference(db, current_user.id, "file_extensions")
    if ext_json:
        try:
            file_extensions = json.loads(ext_json)
        except (json.JSONDecodeError, TypeError):
            file_extensions = DEFAULT_FILE_EXTENSIONS
    else:
        file_extensions = DEFAULT_FILE_EXTENSIONS

    return UserSettingsResponse(
        audio_preferences=audio_prefs,
        anime_detection=anime_detection,
        file_extensions=file_extensions,
    )


@router.put("", response_model=UserSettingsResponse)
async def update_settings(
    updates: UserSettingsUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update user settings."""
    if updates.audio_preferences is not None:
        await set_user_preference(
            db,
            current_user.id,
            "audio_preferences",
            updates.audio_preferences.model_dump_json(),
        )

    if updates.anime_detection is not None:
        await set_user_preference(
            db,
            current_user.id,
            "anime_detection",
            updates.anime_detection.model_dump_json(),
        )

    if updates.file_extensions is not None:
        await set_user_preference(
            db,
            current_user.id,
            "file_extensions",
            json.dumps(updates.file_extensions),
        )

    await db.flush()

    # Return updated settings
    return await get_settings(current_user, db)


@router.delete("")
async def reset_settings(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Reset all settings to defaults."""
    await db.execute(
        delete(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    return {"message": "Settings reset to defaults"}
