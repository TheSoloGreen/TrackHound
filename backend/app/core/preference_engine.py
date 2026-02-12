"""Preference engine for evaluating audio track rules."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AudioPreferences:
    """Audio preference configuration."""
    
    require_english_non_anime: bool = True
    require_japanese_anime: bool = True
    require_dual_audio_anime: bool = True
    check_default_track: bool = True
    preferred_codecs: list[str] = field(default_factory=list)
    auto_fix_english_default_non_anime: bool = False


@dataclass
class Issue:
    """Represents an issue found with a media file's audio tracks."""
    
    severity: str  # "error" or "warning"
    code: str
    message: str


class PreferenceEngine:
    """Engine for evaluating audio preferences against media files."""

    def __init__(self, preferences: Optional[AudioPreferences] = None):
        """
        Initialize preference engine.
        
        Args:
            preferences: Audio preferences to use (defaults to default preferences)
        """
        self.preferences = preferences or AudioPreferences()

    def evaluate(
        self,
        audio_tracks: list[dict],
        is_anime: bool = False,
    ) -> list[str]:
        """
        Evaluate audio tracks against preferences.
        
        Args:
            audio_tracks: List of audio track dicts with language, is_default, codec, etc.
            is_anime: Whether the content is anime
        
        Returns:
            List of issue messages (empty if no issues)
        """
        issues = []
        
        if not audio_tracks:
            issues.append("No audio tracks found")
            return issues
        
        # Get languages present
        languages = set()
        default_language = None
        
        for track in audio_tracks:
            lang = track.get("language")
            if lang:
                languages.add(lang.lower())
            if track.get("is_default"):
                default_language = lang.lower() if lang else None
        
        # Check English requirement for non-anime
        if not is_anime and self.preferences.require_english_non_anime:
            if "en" not in languages:
                issues.append("Missing English audio track")
        
        # Check Japanese requirement for anime
        if is_anime and self.preferences.require_japanese_anime:
            if "ja" not in languages:
                issues.append("Missing Japanese audio track (anime)")
        
        # Check dual audio for anime
        if is_anime and self.preferences.require_dual_audio_anime:
            has_english = "en" in languages
            has_japanese = "ja" in languages
            if not (has_english and has_japanese):
                if not has_english:
                    issues.append("Missing English audio for dual audio (anime)")
                if not has_japanese:
                    issues.append("Missing Japanese audio for dual audio (anime)")
        
        # Check default track
        if self.preferences.check_default_track and default_language:
            if is_anime:
                # For anime, default should be English or Japanese
                if default_language not in ("en", "ja"):
                    issues.append(f"Default audio track is '{default_language}', expected English or Japanese (anime)")
            else:
                # For non-anime, default should be English
                if default_language != "en" and "en" in languages:
                    issues.append(f"Default audio track is '{default_language}', expected English")
        
        # Check preferred codecs
        if self.preferences.preferred_codecs:
            codecs = {track.get("codec", "").lower() for track in audio_tracks if track.get("codec")}
            preferred_lower = {c.lower() for c in self.preferences.preferred_codecs}
            if codecs and not (codecs & preferred_lower):
                issues.append(f"No preferred audio codec found (has: {', '.join(codecs)})")
        
        return issues

    def evaluate_detailed(
        self,
        audio_tracks: list[dict],
        is_anime: bool = False,
    ) -> list[Issue]:
        """
        Evaluate audio tracks and return detailed issues.
        
        Args:
            audio_tracks: List of audio track dicts
            is_anime: Whether the content is anime
        
        Returns:
            List of Issue objects with severity and details
        """
        issues = []
        
        if not audio_tracks:
            issues.append(Issue(
                severity="error",
                code="NO_AUDIO",
                message="No audio tracks found",
            ))
            return issues
        
        # Get languages present
        languages = set()
        default_language = None
        
        for track in audio_tracks:
            lang = track.get("language")
            if lang:
                languages.add(lang.lower())
            if track.get("is_default"):
                default_language = lang.lower() if lang else None
        
        # Check English requirement for non-anime
        if not is_anime and self.preferences.require_english_non_anime:
            if "en" not in languages:
                issues.append(Issue(
                    severity="error",
                    code="MISSING_ENGLISH",
                    message="Missing English audio track",
                ))
        
        # Check Japanese requirement for anime
        if is_anime and self.preferences.require_japanese_anime:
            if "ja" not in languages:
                issues.append(Issue(
                    severity="error",
                    code="MISSING_JAPANESE",
                    message="Missing Japanese audio track (anime)",
                ))
        
        # Check dual audio for anime
        if is_anime and self.preferences.require_dual_audio_anime:
            has_english = "en" in languages
            has_japanese = "ja" in languages
            if not (has_english and has_japanese):
                issues.append(Issue(
                    severity="warning",
                    code="MISSING_DUAL_AUDIO",
                    message="Missing dual audio (English + Japanese) for anime",
                ))
        
        # Check default track
        if self.preferences.check_default_track and default_language:
            if is_anime:
                if default_language not in ("en", "ja"):
                    issues.append(Issue(
                        severity="warning",
                        code="WRONG_DEFAULT_ANIME",
                        message=f"Default audio is '{default_language}', expected English or Japanese",
                    ))
            else:
                if default_language != "en" and "en" in languages:
                    issues.append(Issue(
                        severity="warning",
                        code="WRONG_DEFAULT",
                        message=f"Default audio is '{default_language}', expected English",
                    ))
        
        return issues

    def get_summary(
        self,
        audio_tracks: list[dict],
        is_anime: bool = False,
    ) -> dict:
        """
        Get a summary of the audio track evaluation.
        
        Returns dict with:
            - has_issues: bool
            - issue_count: int
            - error_count: int
            - warning_count: int
            - languages: list of language codes
            - default_language: the default track's language
        """
        issues = self.evaluate_detailed(audio_tracks, is_anime)
        
        languages = []
        default_language = None
        
        for track in audio_tracks:
            lang = track.get("language")
            if lang and lang not in languages:
                languages.append(lang)
            if track.get("is_default"):
                default_language = lang
        
        return {
            "has_issues": len(issues) > 0,
            "issue_count": len(issues),
            "error_count": sum(1 for i in issues if i.severity == "error"),
            "warning_count": sum(1 for i in issues if i.severity == "warning"),
            "languages": languages,
            "default_language": default_language,
        }
