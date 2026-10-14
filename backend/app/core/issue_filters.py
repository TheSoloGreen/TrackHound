"""Shared issue predicates for dashboard counts, file lists, and exports."""
from sqlalchemy import and_, or_, func
from app.models.entities import MediaFile, AudioTrack, MediaIssue
from app.core.analyzer import KNOWN_LANGUAGE_CODES


CATEGORY_CODES = {
    "missing_english": {"MISSING_ENGLISH", "MISSING_DUAL_ENGLISH"},
    "missing_japanese": {"MISSING_JAPANESE", "MISSING_DUAL_JAPANESE"},
    "missing_dual_audio": {"MISSING_DUAL_ENGLISH", "MISSING_DUAL_JAPANESE", "MISSING_DUAL_AUDIO"},
    "preferred_not_default": {"NO_DEFAULT", "MULTIPLE_DEFAULTS", "SPECIAL_DEFAULT", "WRONG_DEFAULT", "WRONG_DEFAULT_ANIME"},
    "unknown_language": {"UNKNOWN_LANGUAGE"},
    "preferred_codec": {"NO_PREFERRED_CODEC"},
}
CATEGORY_CODES["missing_required_audio"] = {"NO_AUDIO"} | CATEGORY_CODES["missing_english"] | CATEGORY_CODES["missing_japanese"] | CATEGORY_CODES["missing_dual_audio"]


def issue_predicate(category):
    structured = MediaFile.issue_records.any(MediaIssue.code.in_(CATEGORY_CODES[category]))
    # Only untouched legacy rows use text. Evaluated records are code-driven.
    return or_(structured, and_(MediaFile.issue_evaluation_version.is_(None), _legacy_predicate(category)),
               and_(MediaFile.issue_evaluation_version == 0, _legacy_predicate(category)) if category == "unknown_language" else False)


def _legacy_predicate(category):
    patterns = {
        "missing_english": ["%Missing English audio%", "%missing_english%", "%No track tagged English%"],
        "missing_japanese": ["%Missing Japanese audio%", "%missing_japanese%", "%No track tagged Japanese%"],
        "missing_dual_audio": ["%dual audio%", "%missing_dual_audio%"],
        "preferred_not_default": ["%Default audio track is '%"],
        "preferred_codec": ["%No preferred audio codec%"],
    }
    if category == "unknown_language":
        return MediaFile.audio_tracks.any(or_(AudioTrack.language.is_(None),
            func.lower(func.trim(AudioTrack.language)).not_in(KNOWN_LANGUAGE_CODES)))
    if category == "missing_required_audio":
        return or_(_legacy_predicate("missing_english"), _legacy_predicate("missing_japanese"),
                   _legacy_predicate("missing_dual_audio"), MediaFile.issue_details.ilike("%No audio tracks found%"))
    return or_(*(MediaFile.issue_details.ilike(pattern) for pattern in patterns[category]))
