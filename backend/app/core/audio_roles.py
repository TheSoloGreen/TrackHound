"""Conservative title-based audio roles and deterministic main-track selection."""

import re

from app.core.analyzer import normalize_language


def audio_role(track: dict) -> str:
    title = str(track.get("title") or "").casefold()
    if re.search(r"\bcommentary\b", title):
        return "commentary"
    if re.search(r"\b(?:audio[ _-]+description|descriptive[ _-]+audio|visually[ _-]+impaired)\b", title):
        return "audio_description"
    return "main"


def select_main_track(audio_tracks: list[dict], language: str, preferred_codecs: list[str] | None = None) -> int | None:
    language = normalize_language(language)
    if language is None:
        return None
    preferred = {codec.casefold() for codec in preferred_codecs or []}
    candidates = [track for track in audio_tracks
                  if normalize_language(track.get("language")) == language and audio_role(track) == "main"
                  and isinstance(track.get("index"), int) and not isinstance(track.get("index"), bool)]
    if not candidates:
        return None
    def rank(track):
        return (bool(track.get("is_default")), str(track.get("codec") or "").casefold() in preferred,
                track.get("channels") or 0, -(track["index"]))
    return max(candidates, key=rank)["index"]
