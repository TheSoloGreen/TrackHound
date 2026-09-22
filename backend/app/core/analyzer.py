"""Audio track analyzer using pymediainfo."""

from typing import Optional


class AudioAnalysisError(RuntimeError):
    """The file could not be analyzed; existing metadata must be retained."""


def require_successful_analysis(result: dict) -> dict:
    """Do not interpret a failed or skipped probe as a file with no audio."""
    problem = result.get("error") or result.get("warning")
    if problem:
        raise AudioAnalysisError(f"Audio analysis failed: {problem}")
    return result

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


# ISO 639-1 tags accepted as known metadata. Raw values remain available for review.
KNOWN_LANGUAGE_CODES = frozenset("aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu".split())


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
    if code in KNOWN_LANGUAGE_CODES:
        return code
    
    # Check mapping
    if code in LANGUAGE_MAP:
        return LANGUAGE_MAP[code]
    
    # Return original if unknown (might be valid ISO 639-1)
    return None


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
                self._mediainfo_available = bool(MediaInfo.can_parse())
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
                    # Safely extract language, handling empty other_language lists
                    other_langs = getattr(track, 'other_language', None)
                    language_raw = track.language or (other_langs[0] if other_langs else None)
                    
                    # Try to detect language from title if not set
                    detected_lang = normalize_language(language_raw)
                    if not detected_lang and track.title:
                        title_lower = track.title.lower()
                        for lang_name, code in LANGUAGE_MAP.items():
                            if lang_name in title_lower and code:
                                detected_lang = code
                                break
                    
                    channels = getattr(track, 'channel_s', None) or 2
                    channel_layout = getattr(track, 'channel_layout', None)
                    
                    # Safely parse bitrate
                    raw_bitrate = getattr(track, 'bit_rate', None)
                    try:
                        bitrate = int(raw_bitrate) if raw_bitrate else None
                    except (ValueError, TypeError):
                        bitrate = None
                    
                    audio_track = {
                        "index": audio_index,
                        "language": detected_lang,
                        "language_raw": language_raw,
                        "codec": track.format or getattr(track, 'codec_id', None),
                        "channels": channels,
                        "channel_layout": parse_channel_layout(channels, channel_layout),
                        "bitrate": bitrate,
                        "is_default": getattr(track, 'default', None) == "Yes" if hasattr(track, 'default') else (audio_index == 0),
                        "is_forced": getattr(track, 'forced', None) == "Yes" if hasattr(track, 'forced') else False,
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
        return language.lower() in [lang.lower() for lang in languages if lang]

    def has_dual_audio(self, file_path: str, lang1: str = "en", lang2: str = "ja") -> bool:
        """Check if file has both specified languages."""
        languages = [lang.lower() for lang in self.get_languages(file_path) if lang]
        return lang1.lower() in languages and lang2.lower() in languages
