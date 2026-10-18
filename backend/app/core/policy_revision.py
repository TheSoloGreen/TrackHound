"""Revision of the rules that actually affect stored audio findings."""

from dataclasses import asdict
import hashlib
import json

from app.core.preference_engine import EVALUATION_VERSION


def evaluation_policy(preferences):
    values = preferences.model_dump() if hasattr(preferences, "model_dump") else asdict(preferences)
    # These govern physical editing/removal suggestions, not issue evaluation.
    values.pop("auto_fix_english_default_non_anime", None)
    values.pop("audio_track_keep_languages", None)
    values["preferred_codecs"] = sorted({codec.casefold() for codec in values["preferred_codecs"]})
    return values


def evaluation_revision(preferences):
    payload = {"policy": evaluation_policy(preferences), "evaluator": EVALUATION_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
