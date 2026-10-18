"""Settings API endpoints for user preferences."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.user_settings import load_user_settings
from app.core import jobs
from app.core.policy_revision import evaluation_revision
from app.core.reevaluation import evaluation_status, reevaluation_payload
from app.models.database import get_db
from app.models.entities import User, UserPreference
from app.models.schemas import (
    UserSettingsResponse,
    UserSettingsUpdate,
    JobResponse,
    EvaluationStatus,
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
    user_id = current_user.id
    async with jobs.job_manager.coordination:
        await db.commit()  # Release authentication's snapshot before serialized writes.
        before = await load_user_settings(db, user_id)
        for key in ("audio_preferences", "anime_detection", "file_extensions"):
            value = getattr(updates, key)
            if value is not None:
                await set_user_preference(db, user_id, key,
                    json.dumps(value) if key == "file_extensions" else value.model_dump_json())
        await db.flush()
        after = await load_user_settings(db, user_id)
        if evaluation_revision(before.audio_preferences) != evaluation_revision(after.audio_preferences):
            await jobs.job_manager.enqueue_locked(db, user_id, "reevaluate", reevaluation_payload(after))
        else:
            await db.commit()
        return after


@router.delete("")
async def reset_settings(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Reset all settings to defaults."""
    user_id = current_user.id
    async with jobs.job_manager.coordination:
        await db.commit()
        before = await load_user_settings(db, user_id)
        await db.execute(delete(UserPreference).where(UserPreference.user_id == user_id))
        after = await load_user_settings(db, user_id)
        if evaluation_revision(before.audio_preferences) != evaluation_revision(after.audio_preferences):
            await jobs.job_manager.enqueue_locked(db, user_id, "reevaluate", reevaluation_payload(after))
        else:
            await db.commit()
    return {"message": "Settings reset to defaults"}


@router.get("/evaluation", response_model=EvaluationStatus)
async def get_evaluation_status(current_user: Annotated[User, Depends(get_current_user)],
                                db: Annotated[AsyncSession, Depends(get_db)]):
    return await evaluation_status(db, current_user.id)


@router.post("/reevaluate", response_model=JobResponse, status_code=202)
async def start_reevaluation(current_user: Annotated[User, Depends(get_current_user)],
                             db: Annotated[AsyncSession, Depends(get_db)]):
    user_id = current_user.id
    async with jobs.job_manager.coordination:
        await db.commit()
        settings = await load_user_settings(db, user_id)
        return await jobs.job_manager.enqueue_locked(db, user_id, "reevaluate", reevaluation_payload(settings))
