"""One structured audio evaluator used by scans, edits, summaries, and reports."""

from dataclasses import asdict, dataclass, field
from typing import Optional

from app.core.analyzer import normalize_language
from app.core.audio_roles import audio_role

EVALUATION_VERSION = 1


@dataclass
class AudioPreferences:
    require_english_non_anime: bool = True
    require_japanese_anime: bool = True
    require_dual_audio_anime: bool = True
    check_default_track: bool = True
    preferred_codecs: list[str] = field(default_factory=list)
    auto_fix_english_default_non_anime: bool = False


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class PreferenceEngine:
    def __init__(self, preferences: Optional[AudioPreferences] = None):
        self.preferences = preferences or AudioPreferences()

    def required_languages(self, is_anime: bool = False) -> set[str]:
        if not is_anime:
            return {"en"} if self.preferences.require_english_non_anime else set()
        required = {"ja"} if self.preferences.require_japanese_anime else set()
        if self.preferences.require_dual_audio_anime:
            required.update({"en", "ja"})
        return required

    def evaluate(self, audio_tracks: list[dict], is_anime: bool = False) -> list[str]:
        return [issue.message for issue in self.evaluate_detailed(audio_tracks, is_anime)]

    def evaluate_detailed(self, audio_tracks: list[dict], is_anime: bool = False) -> list[Issue]:
        if not audio_tracks:
            return [Issue("error", "NO_AUDIO", "No audio tracks found")]
        issues: list[Issue] = []
        main = [track for track in audio_tracks if audio_role(track) == "main"]
        languages = {normalize_language(track.get("language")) for track in main}
        all_languages = {normalize_language(track.get("language")) for track in audio_tracks}
        unknown = None in all_languages

        def missing(language: str, code: str, message: str, *, dual=False):
            if language in languages:
                return
            name = "English" if language == "en" else "Japanese"
            if unknown:
                message = f"No track tagged {name}; audio language needs review" + (" for dual audio (anime)" if dual else "")
            elif language in all_languages:
                message = f"No main {name} audio track found (only commentary or audio description)" + (" for dual audio (anime)" if dual else "")
            issues.append(Issue("error", code, message,
                                {"language": language, "needs_language_review": unknown, "main_audio_required": True}))

        if not is_anime and self.preferences.require_english_non_anime:
            missing("en", "MISSING_ENGLISH", "Missing English audio track")
        if is_anime and self.preferences.require_japanese_anime:
            missing("ja", "MISSING_JAPANESE", "Missing Japanese audio track (anime)")
        if is_anime and self.preferences.require_dual_audio_anime:
            missing("en", "MISSING_DUAL_ENGLISH", "Missing English audio for dual audio (anime)", dual=True)
            missing("ja", "MISSING_DUAL_JAPANESE", "Missing Japanese audio for dual audio (anime)", dual=True)
        if unknown:
            issues.append(Issue("warning", "UNKNOWN_LANGUAGE", "Unknown or unrecognized audio language metadata"))

        if self.preferences.check_default_track:
            defaults = [track for track in audio_tracks if track.get("is_default")]
            if not defaults:
                issues.append(Issue("warning", "NO_DEFAULT", "No default audio track is flagged"))
            elif len(defaults) > 1:
                issues.append(Issue("warning", "MULTIPLE_DEFAULTS", "Multiple audio tracks are flagged as default",
                                    {"track_indices": [track.get("index") for track in defaults]}))
            else:
                track = defaults[0]
                language = normalize_language(track.get("language"))
                role = audio_role(track)
                if role != "main":
                    issues.append(Issue("warning", "SPECIAL_DEFAULT", "Default audio is a commentary or audio description track",
                                        {"track_index": track.get("index"), "role": role}))
                if is_anime and language not in ("en", "ja"):
                    issues.append(Issue("warning", "WRONG_DEFAULT_ANIME",
                                        f"Default audio track is '{language or 'unknown'}', expected English or Japanese (anime)"))
                elif not is_anime and language != "en" and "en" in languages:
                    issues.append(Issue("warning", "WRONG_DEFAULT",
                                        f"Default audio track is '{language or 'unknown'}', expected English"))

        if self.preferences.preferred_codecs:
            codecs = {str(track.get("codec") or "").casefold() for track in main if track.get("codec")}
            preferred = {codec.casefold() for codec in self.preferences.preferred_codecs}
            if not (codecs & preferred):
                issues.append(Issue("warning", "NO_PREFERRED_CODEC",
                                    f"No preferred audio codec found (has: {', '.join(sorted(codecs)) or 'unknown'})",
                                    {"available": sorted(codecs), "preferred": sorted(preferred)}))
        return issues

    def get_summary(self, audio_tracks: list[dict], is_anime: bool = False) -> dict:
        issues = self.evaluate_detailed(audio_tracks, is_anime)
        defaults = [track for track in audio_tracks if track.get("is_default")]
        return {
            "has_issues": bool(issues), "issue_count": len(issues),
            "error_count": sum(issue.severity == "error" for issue in issues),
            "warning_count": sum(issue.severity == "warning" for issue in issues),
            "languages": sorted({track["language"] for track in audio_tracks if track.get("language")}),
            "default_language": defaults[0].get("language") if len(defaults) == 1 else None,
        }
