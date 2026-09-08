"""Read the same validated preferences for the UI and background scans."""

import json

from pydantic import ValidationError
from sqlalchemy import select

from app.models.entities import UserPreference
from app.models.schemas import AudioPreferences, AnimeDetectionSettings, UserSettingsResponse, normalize_file_extensions


async def load_user_settings(db, user_id: int) -> UserSettingsResponse:
    rows = await db.execute(select(UserPreference).where(UserPreference.user_id == user_id).order_by(UserPreference.id))
    saved = {row.key: row.value for row in rows.scalars()}

    def model(key, schema):
        try:
            return schema.model_validate_json(saved[key]) if key in saved else schema()
        except ValidationError:
            return schema()

    extensions = UserSettingsResponse.model_fields["file_extensions"].get_default()
    if "file_extensions" in saved:
        try:
            extensions = normalize_file_extensions(json.loads(saved["file_extensions"]))
        except (ValueError, TypeError):
            pass
    return UserSettingsResponse(
        audio_preferences=model("audio_preferences", AudioPreferences),
        anime_detection=model("anime_detection", AnimeDetectionSettings),
        file_extensions=extensions,
    )
