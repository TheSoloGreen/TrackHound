"""Plex TV identity must not depend on library iteration order."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.core.plex_connector import AmbiguousPlexMatch, PlexConnector


def episode(key, *paths, season=1, number=1):
    return NS(ratingKey=key, title=f"Episode {number}", seasonNumber=season, episodeNumber=number,
              media=[NS(parts=[NS(file=path)]) for path in paths])


def show(key, title, year, *paths, original=None, genres=()):
    return NS(ratingKey=key, title=title, originalTitle=original, year=year,
              genres=[NS(tag=genre) for genre in genres], thumb=f"/library/metadata/{key}/thumb/1",
              episodes=Mock(return_value=[episode(f"{key}01", path) for path in paths]))


def connector(*shows):
    client = PlexConnector("synthetic")
    section = NS(type="show", title="TV", all=Mock(return_value=shows))
    client._server = NS(library=NS(sections=Mock(return_value=[section])),
                        fetchItem=Mock(side_effect=lambda key: next(s for s in shows if s.ratingKey == key)))
    return client


@pytest.mark.parametrize("reverse", [False, True])
def test_generic_episode_names_do_not_match_unrelated_shows(reverse):
    shows = [show(1, "Alpha", 2000, "/plex/Alpha/Season 01/E01.mkv"),
             show(2, "Beta", 2010, "/plex/Beta/Season 01/E01.mkv")]
    client = connector(*reversed(shows) if reverse else shows)
    assert client.find_show_by_file("/mount/Unrelated/Season 01/E01.mkv") is None
    assert client.sync_show_metadata("/mount/Unrelated/Season 01/E01.mkv", "Unrelated") is None
    assert client.find_show_by_file("/mount/Beta/Season 01/E01.mkv").rating_key == "2"


@pytest.mark.parametrize("reverse", [False, True])
def test_exact_path_wins_but_duplicate_relative_identities_need_review(reverse):
    shows = [show(1, "Twin", 2000, "/one/Twin/Season 01/E01.mkv"),
             show(2, "Twin", 2020, "/two/Twin/Season 01/E01.mkv")]
    client = connector(*reversed(shows) if reverse else shows)
    assert client.sync_show_metadata("/two/Twin/Season 01/E01.mkv", "Twin")["plex_rating_key"] == "2"
    assert client.find_show_by_file("/mount/Twin/Season 01/E01.mkv") is None
    # A supplied title must not override ambiguous stronger path evidence.
    with pytest.raises(AmbiguousPlexMatch, match=r"relative path match \(2 titles\)"):
        client.sync_show_metadata("/mount/Twin/Season 01/E01.mkv", "Twin (2020)")


def test_duplicate_exact_path_is_not_resolved_by_a_weaker_title():
    path = "/plex/Shared/Season 01/E01.mkv"
    client = connector(show(1, "Alpha", 2000, path), show(2, "Beta", 2010, path))
    assert client.find_show_by_path_or_title(path, "Alpha") is None
    with pytest.raises(AmbiguousPlexMatch, match="exact path"):
        client.sync_show_metadata(path, "Alpha")


@pytest.mark.parametrize("query, key", [("Twin", None), ("Twin (2000)", "1"),
                                        ("Twin [2020]", "2"), ("Twin (1999)", None)])
def test_remakes_require_explicit_matching_year(query, key):
    client = connector(show(1, "Twin", 2000, "/plex/Twin (2000)/Season 01/E01.mkv"),
                       show(2, "Twin", 2020, "/plex/Twin (2020)/Season 01/E01.mkv"))
    match = client.find_show(query)
    assert (match.rating_key if match else None) == key


def test_original_title_and_derived_alias_collisions_are_retained():
    client = connector(show(1, "Alpha: Origins", 2000, original="Shared"),
                       show(2, "Beta", 2010, original="Shared"),
                       show(3, "Alpha: Returns", 2020))
    assert client.find_show("Shared") is None
    assert client.find_show("Alpha") is None
    assert client.find_show("Alpha: Origins").rating_key == "1"
    assert "shared" not in client.get_all_title_mappings()
    assert "alpha" not in client.get_all_title_mappings()


def test_normalized_title_collisions_are_not_overwritten():
    client = connector(show(1, "A.B", 2000), show(2, "AB", 2001))
    assert client.find_show("A.B") is None
    assert client.match_show("/unknown/file.mkv", "AB").ambiguous


def test_fuzzy_candidates_need_uniqueness_not_just_the_highest_score():
    client = connector(show(1, "The Expanse", 2015), show(2, "The Expanse: Origins", 2020))
    assert client.find_show("The Expans") is None
    assert connector(show(1, "The Expanse", 2015)).find_show("The Expans").rating_key == "1"


def test_exact_parsed_title_precedes_fuzzy_folder_name():
    client = connector(show(1, "The Expanse", 2015), show(2, "Beta", 2020))
    assert client.find_show_by_path_or_title("/mount/The Expans/Season 01/E01.mkv", "Beta").rating_key == "2"


@pytest.mark.parametrize("path", ["/mount/Alpha/E01.mkv", r"Z:\mount\Alpha\E01.mkv",
                                  "/mount/Alpha/Specials/E01.mkv", "/mount/Alpha/S00/E01.mkv"])
def test_flat_and_specials_paths_use_the_show_folder(path):
    client = connector(show(1, "Alpha", 2000))
    assert client.find_show_by_path_or_title(path).rating_key == "1"


def test_multiple_versions_of_one_identity_are_not_ambiguous():
    client = connector(show(1, "Alpha", 2000, "/one/Alpha/Season 01/E01.mkv",
                            "/two/Alpha/Season 01/E01.mkv"))
    assert client.find_show_by_file("/mount/Alpha/Season 01/E01.mkv").rating_key == "1"


def test_reloading_inventory_replaces_stale_aliases_and_deduplicates():
    client = connector(show(1, "Alpha", 2000))
    assert client.find_show("Alpha").rating_key == "1"
    section = client._server.library.sections.return_value[0]
    section.all.return_value = [show(2, "Beta", 2010)]
    client.get_tv_shows("TV")
    assert client.find_show("Alpha") is None
    assert client.find_show("Beta").rating_key == "2"
    assert len(client._shows_by_key) == 1


def test_failed_inventory_does_not_publish_partial_matches_or_log_credentials():
    broken = show(2, "Beta", 2010)
    broken.episodes.side_effect = RuntimeError("https://plex.invalid?X-Plex-Token=synthetic-secret")
    client = connector(show(1, "Alpha", 2000), broken)
    with pytest.raises(RuntimeError, match="inventory is unavailable") as error:
        client.find_show("Alpha")
    assert "synthetic-secret" not in str(error.value)
    assert not client._library_loaded and not client._shows_cache


def test_episode_matching_uses_all_media_parts_and_rejects_duplicate_paths():
    title = show(1, "Alpha", 2000, "/plex/Alpha/Season 01/E01.mkv", "/plex/Alpha/Season 02/E01.mkv")
    title.episodes.return_value = [
        episode(101, "/plex/Alpha/Season 01/E01.mkv", "/other/Alpha/Season 01/alternate.mkv"),
        episode(201, "/plex/Alpha/Season 02/E01.mkv", season=2),
    ]
    client = connector(title)
    assert client.match_file_to_episode("/mount/Alpha/Season 02/E01.mkv").rating_key == "201"
    assert client.match_file_to_episode("/other/Alpha/Season 01/alternate.mkv", "Alpha").rating_key == "101"
    title.episodes.return_value.append(episode(102, "/plex/Alpha/Season 01/E01.mkv", number=2))
    assert client.match_file_to_episode("/plex/Alpha/Season 01/E01.mkv") is None
