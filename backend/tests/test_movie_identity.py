from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select
from app.core import scanner
from app.models.entities import Show
from test_scanner_run_scan import library, write_media, files, run


@pytest.mark.asyncio
async def test_remakes_keep_distinct_identities_across_full_rescans(library, monkeypatch):
    write_media(library.root, "Dune (1984)/old.mkv")
    write_media(library.root, "Dune (2021)/new.mkv")
    async with library.sessions() as db:
        location = await db.get(type(library.location), library.location.id)
        location.media_type = "movie"
        await db.commit()
    monkeypatch.setattr(scanner, "PlexConnector", lambda _: NS(sync_movie_metadata=lambda file_path, title_from_path: {
        "title": "Dune", "plex_rating_key": "1" if "1984" in file_path else "2", "is_anime": False}))
    assert (await run(library, token="synthetic")).outcome == "completed"
    first_ids = [file.show_id for file in await files(library)]
    assert len(set(first_ids)) == 2
    assert (await run(library, token="synthetic")).outcome == "completed"
    assert [file.show_id for file in await files(library)] == first_ids
    async with library.sessions() as db:
        assert set(await db.scalars(select(Show.plex_rating_key))) == {"1", "2"}


@pytest.mark.asyncio
async def test_enrichment_preserves_local_title_and_replacement_changes_identity(library, monkeypatch):
    write_media(library.root, "Movie (2000)/movie.mkv")
    async with library.sessions() as db:
        location = await db.get(type(library.location), library.location.id)
        location.media_type = "movie"
        await db.commit()
    await run(library)
    local_id = (await files(library))[0].show_id
    metadata = {"title": "Movie", "plex_rating_key": "1", "is_anime": False}
    monkeypatch.setattr(scanner, "PlexConnector", lambda _: NS(sync_movie_metadata=lambda **_: metadata))
    await run(library, token="synthetic")
    assert (await files(library))[0].show_id == local_id
    metadata["plex_rating_key"] = "2"
    await run(library, token="synthetic")
    assert (await files(library))[0].show_id != local_id
    async with library.sessions() as db:
        assert list(await db.scalars(select(Show.plex_rating_key))) == ["2"]
