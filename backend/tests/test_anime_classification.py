"""Conservative anime hints for TV, movies, and local folder names."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.core.classification import anime_folder_match
from app.core.plex_connector import PlexConnector
from app.models.schemas import AnimeDetectionSettings


@pytest.mark.parametrize("kind", ["show", "movie"])
@pytest.mark.parametrize("genres, expected", [
    (["Animation", "Family"], False),
    (["Japanese Animation"], False),
    (["Animation", "Anime"], True),
    ([" アニメ "], True),
    ([" ANIME "], True),
])
def test_explicit_anime_genres_for_tv_and_movies(kind, genres, expected):
    path = "/plex/Example/Season 01/E01.mkv"
    episode = NS(media=[NS(parts=[NS(file=path)])])
    title = NS(ratingKey=1, title="Example", originalTitle=None, year=2020,
               genres=[NS(tag=genre) for genre in genres], thumb=None, thumbUrl=None,
               episodes=Mock(return_value=[episode]), media=episode.media)
    section = NS(type=kind, all=Mock(return_value=[title]))
    connector = PlexConnector("synthetic")
    connector._server = NS(library=NS(sections=Mock(return_value=[section])))
    lookup = connector.sync_movie_metadata if kind == "movie" else connector.sync_show_metadata
    assert lookup(path, "Example")["is_anime"] is expected


def test_custom_genres_are_exact_normalized_and_can_be_disabled():
    configured = AnimeDetectionSettings(anime_genres=[" Japanese Animation ", "ANIME", "anime", ""])
    assert configured.anime_genres == ["japanese animation", "anime"]
    connector = PlexConnector("synthetic", anime_genres=configured.anime_genres)
    assert connector._is_anime(["Japanese Animation"])
    assert not connector._is_anime(["Animation"])
    assert not PlexConnector("synthetic", anime_genres=[])._is_anime(["Anime"])


@pytest.mark.parametrize("path, expected", [
    ("/media/Animation/Show/E01.mkv", False),
    ("/media/NotAnime/Show/E01.mkv", False),
    ("/media/Show/anime.mkv", False),
    ("/media/Anime/Show/E01.mkv", True),
    ("/media/Anime_Movies/Film.mkv", True),
    (r"C:\media\Anime-TV\Show\E01.mkv", True),
])
def test_default_folder_terms_require_explicit_anime_evidence(path, expected):
    assert AnimeDetectionSettings().anime_folder_keywords == ["anime"]
    assert anime_folder_match(path, AnimeDetectionSettings().anime_folder_keywords) is expected


def test_saved_custom_folder_keywords_remain_explicit_opt_ins():
    settings = AnimeDetectionSettings.model_validate({"anime_folder_keywords": ["anime", "animation"]})
    assert settings.anime_folder_keywords == ["anime", "animation"]
    assert settings.anime_genres == ["anime", "アニメ"]
    assert anime_folder_match("/media/Animation/Show/E01.mkv", settings.anime_folder_keywords)
