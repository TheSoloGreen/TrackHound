"""Keep the library category and the audio-analysis classification in agreement."""

import re


def anime_folder_match(file_path: str, keywords: list[str]) -> bool:
    """Match configured terms in folder names without matching unrelated substrings."""
    folders = re.split(r"[/\\]", file_path)[:-1]
    return any(
        re.search(r"(?<!\w)" + re.escape(keyword.casefold().replace("_", " ")) + r"(?!\w)",
                  folder.casefold().replace("_", " "))
        for folder in folders for keyword in keywords if keyword
    )


def classify_show(show, is_anime: bool, source: str | None, base_media_type: str | None = None):
    base = base_media_type or show.base_media_type or ("movie" if show.media_type == "movie" else "tv")
    show.base_media_type = base
    show.media_type = "anime" if is_anime else base
    show.is_anime = is_anime
    show.anime_source = source if is_anime or source == "manual" else None
