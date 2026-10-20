"""Ambiguous enrichment reports review information without stopping local scans."""

from unittest.mock import Mock
import json

import pytest
from sqlalchemy import select

from app.core import scanner
from app.core.encryption import encrypt_value
from app.core.scan_state import scan_state_manager
from app.models.entities import ScanLocation, Show, User, UserPreference
from test_scanner_run_scan import library, write_media, files, run
from test_jobs import database, queue, enqueue_scan, execute_next  # noqa: F401
from test_tv_metadata import connector, show


@pytest.mark.asyncio
async def test_ambiguous_file_warns_skips_autofix_and_does_not_disable_other_matches(library, monkeypatch):
    ambiguous = write_media(library.root, "Twin/Season 01/E01.mkv")
    other = write_media(library.root, "Zebra/Season 01/E01.mkv")
    client = connector(show(1, "Twin", 2000, "/one/Twin/Season 01/E01.mkv"),
                       show(2, "Twin", 2020, "/two/Twin/Season 01/E01.mkv"),
                       show(3, "Zebra canonical", 2021, str(other)))
    monkeypatch.setattr(scanner, "PlexConnector", lambda *_, **__: client)
    autofix = Mock(side_effect=lambda path, audio, is_anime: audio)
    monkeypatch.setattr(scanner.MediaScanner, "_auto_fix_default_track", staticmethod(autofix))
    status = await run(library, token="synthetic")
    assert status.outcome == "completed_with_errors" and status.error_count == 0
    assert status.warning_count == 1 and str(ambiguous) in status.warnings[0]
    assert "2 titles" in status.warnings[0] and "not applied" in status.warnings[0]
    assert len(await files(library)) == 2
    assert [call.args[0] for call in autofix.call_args_list] == [str(other)]
    async with library.sessions() as db:
        titles = {title.title: title.plex_rating_key for title in await db.scalars(select(Show))}
    assert titles == {"Twin": None, "Zebra canonical": "3"}


@pytest.mark.asyncio
async def test_ambiguous_rescan_preserves_existing_plex_identity_and_anime_classification(library, monkeypatch):
    source = write_media(library.root)
    first = connector(show(1, "Canonical anime", 2000, str(source), genres=["Anime"]))
    monkeypatch.setattr(scanner, "PlexConnector", lambda *_, **__: first)
    await run(library, token="synthetic")
    show_id = (await files(library))[0].show_id
    ambiguous = connector(show(1, "Canonical anime", 2000, str(source), genres=["Anime"]),
                          show(2, "Conflicting title", 2020, str(source)))
    monkeypatch.setattr(scanner, "PlexConnector", lambda *_, **__: ambiguous)
    autofix = Mock(side_effect=AssertionError("An ambiguous file must never be automatically edited"))
    monkeypatch.setattr(scanner.MediaScanner, "_auto_fix_default_track", autofix)
    status = await run(library, token="synthetic")
    assert status.warning_count == 1 and status.error_count == 0
    assert (await files(library))[0].show_id == show_id
    autofix.assert_not_called()
    async with library.sessions() as db:
        title = await db.get(Show, show_id)
        assert title.title == "Canonical anime" and title.plex_rating_key == "1"
        assert title.is_anime and title.anime_source == "plex_genre"
        assert title.thumb_url == "/library/metadata/1/thumb/1"


@pytest.mark.asyncio
async def test_tv_remakes_keep_distinct_ids_across_rescans(library, monkeypatch):
    old = write_media(library.root, "Twin (2000)/Season 01/E01.mkv")
    new = write_media(library.root, "Twin (2020)/Season 01/E01.mkv")
    client = connector(show(1, "Twin", 2000, str(old)), show(2, "Twin", 2020, str(new)))
    monkeypatch.setattr(scanner, "PlexConnector", lambda *_, **__: client)
    assert (await run(library, token="synthetic")).outcome == "completed"
    first_ids = [file.show_id for file in await files(library)]
    assert len(set(first_ids)) == 2
    assert (await run(library, token="synthetic")).outcome == "completed"
    assert [file.show_id for file in await files(library)] == first_ids


@pytest.mark.asyncio
async def test_ambiguity_warning_survives_job_and_scan_state_reset(queue, monkeypatch):
    source = queue.source.parent / "Twin" / "Season 01" / "E01.mkv"
    source.parent.mkdir(parents=True)
    queue.source.replace(source)
    async with queue.sessions() as db:
        location = await db.get(ScanLocation, queue.location.id)
        location.media_type = "tv"
        user = await db.get(User, queue.user.id)
        user.plex_token = encrypt_value("synthetic")
        db.add(UserPreference(user_id=user.id, key="audio_preferences",
                              value=json.dumps({"auto_fix_english_default_non_anime": True})))
        await db.commit()
    client = connector(show(1, "Twin", 2000, "/one/Twin/Season 01/E01.mkv"),
                       show(2, "Twin", 2020, "/two/Twin/Season 01/E01.mkv"))
    monkeypatch.setattr(scanner, "PlexConnector", lambda *_, **__: client)
    autofix = Mock(side_effect=AssertionError("Even opt-in automatic edits must be skipped"))
    monkeypatch.setattr(scanner.MediaScanner, "_auto_fix_default_track", autofix)
    await enqueue_scan(queue)
    job = await execute_next(queue)
    assert job.status == "completed_with_errors"
    assert job.progress["warning_count"] == 1 and job.progress["error_count"] == 0
    autofix.assert_not_called()
    await scan_state_manager.reset()
    status = (await queue.client.get("/api/scan/status")).json()
    assert status["warnings"] == job.progress["warnings"]
    assert str(source) in status["warnings"][0]
    saved = (await queue.client.get(f"/api/jobs/{job.id}")).json()
    assert saved["progress"]["warnings"] == status["warnings"]
