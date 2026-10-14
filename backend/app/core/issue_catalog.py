"""Persist evaluator output and conservatively translate historical issue text."""

import re

from app.core.preference_engine import EVALUATION_VERSION, Issue
from app.models.entities import MediaIssue


def apply_evaluation(media_file, engine, tracks, is_anime=False):
    issues = engine.evaluate_detailed(tracks, is_anime)
    previous = {record.code: record for record in media_file.issue_records}
    records = []
    for issue in issues:
        record = previous.get(issue.code) or MediaIssue(code=issue.code)
        record.severity, record.message, record.details = issue.severity, issue.message, issue.details
        records.append(record)
    media_file.issue_records = records
    media_file.issue_evaluation_version = EVALUATION_VERSION
    media_file.has_issues = bool(issues)
    media_file.issue_details = "; ".join(issue.message for issue in issues) or None
    return issues


def legacy_issues(message, has_issues=True):
    """Retain unknown historical findings instead of silently dismissing them."""
    if not message:
        return [Issue("warning", "LEGACY_REVIEW", "Previously flagged issue needs reevaluation", {"legacy": True})] if has_issues else []
    records = {}
    for part in re.split(r"; (?=Missing |No track |Default |Unknown |No audio |No preferred )", message):
        lower = part.casefold()
        if "dual audio" in lower or "missing_dual_audio" in lower:
            code = "MISSING_DUAL_ENGLISH" if "english audio" in lower or "tagged english" in lower else "MISSING_DUAL_JAPANESE" if "japanese audio" in lower or "tagged japanese" in lower else "MISSING_DUAL_AUDIO"
        elif "missing english" in lower or "missing_english" in lower or "tagged english" in lower:
            code = "MISSING_ENGLISH"
        elif "missing japanese" in lower or "missing_japanese" in lower or "tagged japanese" in lower:
            code = "MISSING_JAPANESE"
        elif "no audio tracks" in lower:
            code = "NO_AUDIO"
        elif "default audio" in lower:
            code = "WRONG_DEFAULT_ANIME" if "anime" in lower else "WRONG_DEFAULT"
        elif "unknown" in lower and "language" in lower:
            code = "UNKNOWN_LANGUAGE"
        elif "no preferred audio codec" in lower:
            code = "NO_PREFERRED_CODEC"
        else:
            code = "LEGACY_REVIEW"
        # Multiple legacy descriptions for a code retain all of their wording.
        if code in records:
            records[code].message += "; " + part
        else:
            records[code] = Issue("error" if code.startswith("MISSING_") or code == "NO_AUDIO" else "warning", code, part, {"legacy": True})
    return list(records.values())
