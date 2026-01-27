"""Audio track analyzer using pymediainfo."""

from typing import Optional

# Language code mappings
LANGUAGE_MAP = {
    # ISO 639-2 to ISO 639-1
    "eng": "en",
    "jpn": "ja",
    "ger": "de",
    "deu": "de",
    "fre": "fr",
    "fra": "fr",
    "spa": "es",
    "ita": "it",
    "por": "pt",
    "rus": "ru",
    "chi": "zh",
    "zho": "zh",
    "kor": "ko",
    "ara": "ar",
    "hin": "hi",
    "pol": "pl",
    "dut": "nl",
    "nld": "nl",
    "swe": "sv",
    "nor": "no",
    "dan": "da",
    "fin": "fi",
    "tur": "tr",
    "heb": "he",
    "tha": "th",
    "vie": "vi",
    "ind": "id",
    "msa": "ms",
    "fil": "tl",
    "und": None,  # Undefined
    # Full names
    "english": "en",
    "japanese": "ja",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "chinese": "zh",
    "korean": "ko",
    "arabic": "ar",
    "hindi": "hi",
}


def normalize_language(lang_code: Optional[str]) -> Optional[str]:
    """
    Normalize language code to ISO 639-1 (2-letter) format.
    
    Handles:
    - ISO 639-1 (2-letter): en, ja, de
    - ISO 639-2 (3-letter): eng, jpn, ger
    - Full names: English, Japanese
    - Undefined: und, None, ""
    """
    if not lang_code:
        return None
    
    code = lang_code.lower().strip()
    
    # Already ISO 639-1
    if len(code) == 2 and code != "un":
        return code
    
    # Check mapping
    if code in LANGUAGE_MAP:
        return LANGUAGE_MAP[code]
    
    # Return original if unknown (might be valid ISO 639-1)
    return code[:2] if len(code) >= 2 else None


def parse_channel_layout(channels: int, layout: Optional[str] = None) -> str:
    """Convert channel count to readable format."""
    if layout:
        return layout
    
    channel_map = {
        1: "1.0",
        2: "2.0",
        3: "2.1",
        6: "5.1",
        7: "6.1",
        8: "7.1",
    }
    return channel_map.get(channels, f"{channels}ch")


class AudioAnalyzer:
    """Analyzer for extracting audio track information from media files."""

    def __init__(self):
        self._mediainfo_available = None

    def _check_mediainfo(self) -> bool:
        """Check if pymediainfo is available and working."""
        if self._mediainfo_available is None:
            try:
                from pymediainfo import MediaInfo
                # Try to parse nothing to see if libmediainfo is installed
                MediaInfo.can_parse()
                self._mediainfo_available = True
            except Exception:
                self._mediainfo_available = False
        return self._mediainfo_available

    def analyze(self, file_path: str) -> dict:
        """
        Analyze a media file and extract audio track information.
        
        Returns:
            dict with keys:
                - container: Container format (e.g., "Matroska")
                - duration_ms: Duration in milliseconds
                - audio_tracks: List of audio track dicts
        """
        if not self._check_mediainfo():
            # Fallback if mediainfo not available
            return self._fallback_analyze(file_path)

        try:
            from pymediainfo import MediaInfo
            
            media_info = MediaInfo.parse(file_path)
            
            result = {
                "container": None,
                "duration_ms": None,
                "audio_tracks": [],
            }
            
            # Get general info
            for track in media_info.tracks:
                if track.track_type == "General":
                    result["container"] = track.format
                    if track.duration:
                        result["duration_ms"] = int(float(track.duration))
                    break
            
            # Get audio tracks
            audio_index = 0
            for track in media_info.tracks:
                if track.track_type == "Audio":
                    language_raw = track.language or track.other_language[0] if track.other_language else None
                    
                    # Try to detect language from title if not set
                    detected_lang = normalize_language(language_raw)
                    if not detected_lang and track.title:
                        title_lower = track.title.lower()
                        for lang_name, code in LANGUAGE_MAP.items():
                            if lang_name in title_lower and code:
                                detected_lang = code
                                break
                    
                    channels = track.channel_s or 2
                    channel_layout = track.channel_layout if hasattr(track, 'channel_layout') else None
                    
                    audio_track = {
                        "index": audio_index,
                        "language": detected_lang,
                        "language_raw": language_raw,
                        "codec": track.format or track.codec_id,
                        "channels": channels,
                        "channel_layout": parse_channel_layout(channels, channel_layout),
                        "bitrate": int(track.bit_rate) if track.bit_rate else None,
                        "is_default": track.default == "Yes" if hasattr(track, 'default') else (audio_index == 0),
                        "is_forced": track.forced == "Yes" if hasattr(track, 'forced') else False,
                        "title": track.title,
                    }
                    result["audio_tracks"].append(audio_track)
                    audio_index += 1
            
            return result
            
        except Exception as e:
            # If analysis fails, return minimal info
            return {
                "container": None,
                "duration_ms": None,
                "audio_tracks": [],
                "error": str(e),
            }

    def _fallback_analyze(self, file_path: str) -> dict:
        """Fallback analysis when pymediainfo is not available."""
        import os
        
        # Try to detect container from extension
        ext = os.path.splitext(file_path)[1].lower()
        container_map = {
            ".mkv": "Matroska",
            ".mp4": "MPEG-4",
            ".m4v": "MPEG-4",
            ".avi": "AVI",
            ".mov": "QuickTime",
            ".wmv": "Windows Media",
        }
        
        return {
            "container": container_map.get(ext),
            "duration_ms": None,
            "audio_tracks": [],
            "warning": "pymediainfo not available - audio analysis skipped",
        }

    def get_languages(self, file_path: str) -> list[str]:
        """Get list of audio languages in a file."""
        info = self.analyze(file_path)
        languages = []
        for track in info.get("audio_tracks", []):
            lang = track.get("language")
            if lang and lang not in languages:
                languages.append(lang)
        return languages

    def has_language(self, file_path: str, language: str) -> bool:
        """Check if file has audio track in specified language."""
        languages = self.get_languages(file_path)
        return language.lower() in [l.lower() for l in languages if l]

    def has_dual_audio(self, file_path: str, lang1: str = "en", lang2: str = "ja") -> bool:
        """Check if file has both specified languages."""
        languages = [l.lower() for l in self.get_languages(file_path) if l]
        return lang1.lower() in languages and lang2.lower() in languages
