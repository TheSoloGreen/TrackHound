"""Keep the library category and the audio-analysis classification in agreement."""


def classify_show(show, is_anime: bool, source: str | None, base_media_type: str | None = None):
    base = base_media_type or show.base_media_type or ("movie" if show.media_type == "movie" else "tv")
    show.base_media_type = base
    show.media_type = "anime" if is_anime else base
    show.is_anime = is_anime
    show.anime_source = source if is_anime or source == "manual" else None
