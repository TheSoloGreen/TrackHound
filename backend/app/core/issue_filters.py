"""Shared issue predicates for dashboard counts, file lists, and exports."""
from sqlalchemy import or_, func
from app.models.entities import MediaFile, AudioTrack
from app.core.analyzer import KNOWN_LANGUAGE_CODES


def issue_predicate(category):
    patterns = {
        "missing_english": ["%Missing English audio%", "%missing_english%", "%No track tagged English%"],
        "missing_japanese": ["%Missing Japanese audio%", "%missing_japanese%", "%No track tagged Japanese%"],
        "missing_dual_audio": ["%dual audio%", "%missing_dual_audio%"],
        "preferred_not_default": ["%Default audio track is '%"],
    }
    if category == "unknown_language":
        return MediaFile.audio_tracks.any(or_(AudioTrack.language.is_(None),
            func.lower(func.trim(AudioTrack.language)).not_in(KNOWN_LANGUAGE_CODES)))
    if category == "missing_required_audio":
        return or_(issue_predicate("missing_english"), issue_predicate("missing_japanese"),
                   issue_predicate("missing_dual_audio"), MediaFile.issue_details.ilike("%No audio tracks found%"))
    return or_(*(MediaFile.issue_details.ilike(pattern) for pattern in patterns[category]))
