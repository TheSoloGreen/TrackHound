from types import SimpleNamespace as NS
from unittest.mock import Mock
from app.core.plex_connector import PlexConnector


def movie(key, title, year, path):
    return NS(ratingKey=key, title=title, year=year, genres=[], thumbUrl=f'poster-{key}',
              media=[NS(parts=[NS(file=path)])])


def connector(*movies):
    client = PlexConnector('test')
    tv = NS(type='show', all=Mock(side_effect=AssertionError('Must not consult TV titles')))
    section = NS(type='movie', all=Mock(return_value=movies))
    client._server = NS(library=NS(sections=Mock(return_value=[tv, section])))
    return client


def test_movie_paths_win_and_do_not_use_tv_cache():
    client = connector(movie(1, 'Movie', 2000, '/plex/movie.mkv'))
    assert client.sync_movie_metadata('/plex/movie.mkv', 'Different filename')['plex_rating_key'] == '1'
    assert client.sync_movie_metadata('/mount/Movie (2000).mkv', 'Movie (2000)')['thumb_url'] == 'poster-1'
    client._server.library.sections.assert_called_once()


def test_remakes_require_year_when_title_is_ambiguous():
    client = connector(movie(1, 'Dune', 1984, '/plex/old.mkv'), movie(2, 'Dune', 2021, '/plex/new.mkv'))
    assert client.sync_movie_metadata('/mount/a.mkv', 'Dune') is None
    assert client.sync_movie_metadata('/mount/a.mkv', 'Dune (2021)')['plex_rating_key'] == '2'
    assert client.sync_movie_metadata('/mount/a.mkv', 'Dune (1990)') is None
    assert client.sync_movie_metadata('/mount/a.mkv', 'Unknown') is None


def test_empty_movie_library_is_cached():
    client = connector()
    assert client.sync_movie_metadata('/media/x.mkv', 'X') is None
    assert client.sync_movie_metadata('/media/y.mkv', 'Y') is None
    client._server.library.sections.assert_called_once()
