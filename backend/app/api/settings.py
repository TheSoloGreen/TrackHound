"""Settings API endpoints for user preferences."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.user_settings import load_user_settings
from app.models.database import get_db
from app.models.entities import User, UserPreference
from app.models.schemas import (
    UserSettingsResponse,
    UserSettingsUpdate,
)

router = APIRouter()

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
    return await load_user_settings(db, current_user.id)


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
