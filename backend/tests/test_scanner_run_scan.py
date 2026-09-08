"""Exercise complete scans against a real database and isolated media directories."""

from datetime import datetime
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from threading import Event
from fastapi import BackgroundTasks

import pytest
import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker
from plexapi.exceptions import Unauthorized
from requests.exceptions import Timeout

from app.api import media, settings as settings_api, scan as scan_api
from app.core import scanner as scanning
from app.core.scan_state import scan_state_manager
from app.models.engine import create_database_engine
from app.models.entities import Base, User, UserPreference, ScanLocation, Show, Season, MediaFile, AudioTrack
from app.models.schemas import UserSettingsUpdate, ShowUpdate, ScanStartRequest

ENGLISH = {"container": "Matroska", "audio_tracks": [{"index": 0, "language": "en", "is_default": True}]}
JAPANESE = {"container": "Matroska", "audio_tracks": [{"index": 0, "language": "ja", "is_default": True}]}


def write_media(root, relative="Show/Season 01/E01.mkv"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"media fixture; audio probes are mocked")
    return path


@pytest_asyncio.fixture
async def library(tmp_path, monkeypatch):
    root = tmp_path / "media"
    root.mkdir()
    engine = create_database_engine(f"sqlite+aiosqlite:///{tmp_path / 'library.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = User(plex_user_id="123", plex_username="owner", plex_token="test")
        db.add(user)
        await db.flush()
        location = ScanLocation(user_id=user.id, path=str(root), label="Library", media_type="tv")
        db.add(location)
        db.add(UserPreference(user_id=user.id, key="anime_detection", value='{"anime_folder_keywords":[]}'))
        await db.commit()
    monkeypatch.setattr(scanning, "async_session_maker", sessions)
    monkeypatch.setattr(scanning.AudioAnalyzer, "analyze", lambda *_: ENGLISH)
    await scan_state_manager.reset()
    yield SimpleNamespace(root=root, sessions=sessions, user=user, location=location)
    await scan_state_manager.reset()
    await engine.dispose()


async def run(library, *, incremental=False, roots=None, token=None):
    roots = roots or [str(library.root)]
    async with library.sessions() as db:
        locations = (await db.scalars(select(ScanLocation).where(ScanLocation.user_id == library.user.id, ScanLocation.path.in_(roots)))).all()
    await scan_state_manager.start_scan(library.user.id)
    await scanning.run_scan(roots, {location.path: location.media_type for location in locations}, library.user.id,
                            incremental=incremental, user_plex_token=token)
    return await scan_state_manager.get_status(library.user.id)


async def files(library):
    async with library.sessions() as db:
        return (await db.scalars(select(MediaFile).where(MediaFile.user_id == library.user.id).order_by(MediaFile.id))).all()


async def settings(library, **updates):
    async with library.sessions() as db:
        result = await settings_api.update_settings(UserSettingsUpdate(**updates), library.user, db)
        await db.commit()
        return result


@pytest.mark.asyncio
async def test_full_scan_reanalyzes_unchanged_files_but_incremental_scan_skips(library):
    write_media(library.root)
    first = await run(library)
    assert first.outcome == "completed"
    before = (await files(library))[0]
    with patch.object(scanning.AudioAnalyzer, "analyze", return_value=JAPANESE) as analyze:
        await run(library, incremental=True)
        analyze.assert_not_called()
        assert (await files(library))[0].last_scanned == before.last_scanned
        await run(library, incremental=False)
        analyze.assert_called_once()
    after = (await files(library))[0]
    assert after.last_scanned > before.last_scanned
    assert "Missing English" in after.issue_details
    async with library.sessions() as db:
        assert await db.scalar(select(AudioTrack.language)) == "ja"


@pytest.mark.asyncio
async def test_size_change_is_detected_even_when_mtime_is_unchanged(library):
    source = write_media(library.root)
    await run(library)
    before = source.stat()
    source.write_bytes(b"different size")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    with patch.object(scanning.AudioAnalyzer, "analyze", return_value=JAPANESE) as analyze:
        await run(library, incremental=True)
        analyze.assert_called_once()
    assert (await files(library))[0].file_size == len(b"different size")


@pytest.mark.asyncio
async def test_saved_extensions_control_discovery_without_deleting_ignored_existing_files(library):
    write_media(library.root)
    await run(library)
    mp4 = write_media(library.root, "Show/Season 01/E02.MP4")
    saved = await settings(library, file_extensions=[" MP4 ", ".mp4"])
    assert saved.file_extensions == [".mp4"]
    with patch.object(scanning.AudioAnalyzer, "analyze", return_value=ENGLISH) as analyze:
        status = await run(library)
        analyze.assert_called_once_with(str(mp4))
    assert status.files_total == 1
    assert len(await files(library)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [Timeout("offline"), Unauthorized("expired"), ValueError("No Plex server found")])
async def test_plex_outage_does_not_skip_local_files_or_repeat_warnings(library, failure):
    write_media(library.root)
    write_media(library.root, "Show/Season 01/E02.mkv")
    with patch.object(scanning, "PlexConnector") as plex:
        plex.return_value.sync_show_metadata.side_effect = failure
        status = await run(library, token="synthetic-test-token")
        plex.return_value.sync_show_metadata.assert_called_once()
    assert len(await files(library)) == 2
    assert status.error_count == 0
    assert status.warning_count == 1
    assert "Local scanning continues" in status.warnings[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("use_genres", [True, False])
async def test_saved_plex_genre_toggle_controls_classification(library, use_genres):
    write_media(library.root)
    await settings(library, anime_detection={"use_plex_genres": use_genres, "anime_folder_keywords": []})
    with patch.object(scanning, "PlexConnector") as plex:
        plex.return_value.sync_show_metadata.return_value = {"title": "Plex title", "is_anime": True, "plex_rating_key": "12"}
        await run(library, token="synthetic-test-token")
    async with library.sessions() as db:
        show = await db.scalar(select(Show))
        assert show.is_anime is use_genres
        assert show.media_type == ("anime" if use_genres else "tv")
        assert show.anime_source == ("plex_genre" if use_genres else None)


@pytest.mark.asyncio
async def test_saved_folder_keywords_and_explicit_anime_location(library):
    write_media(library.root, "Cartoons/Season 01/E01.mkv")
    await settings(library, anime_detection={"use_plex_genres": False, "anime_folder_keywords": [" CARTOONS "]})
    await run(library)
    async with library.sessions() as db:
        assert (await db.scalar(select(Show))).anime_source == "folder"
    await settings(library, anime_detection={"use_plex_genres": False, "anime_folder_keywords": []})
    await run(library)
    async with library.sessions() as db:
        assert (await db.scalar(select(Show))).media_type == "tv"
        location = await db.get(ScanLocation, library.location.id)
        location.media_type = "anime"
        await db.commit()
    await run(library)
    async with library.sessions() as db:
        show = await db.scalar(select(Show))
        assert show.media_type == "anime" and show.anime_source == "location"


@pytest.mark.asyncio
@pytest.mark.parametrize("base_type", ["tv", "movie"])
async def test_manual_classification_updates_analysis_stats_and_survives_rescans(library, base_type):
    write_media(library.root)
    async with library.sessions() as db:
        (await db.get(ScanLocation, library.location.id)).media_type = base_type
        await db.commit()
    await run(library)
    async with library.sessions() as db:
        show = await db.scalar(select(Show))
        response = await media.update_show(show.id, ShowUpdate(is_anime=True), library.user, db)
        assert response.media_type == "anime" and response.base_media_type == base_type
        assert response.issues_count == 1
        stats = await media.get_dashboard_stats(library.user, db)
        assert stats.anime_count == 1
        assert stats.total_files_with_issues == 1
        await db.commit()
        show_id = show.id
    with patch.object(scanning.MediaScanner, "_auto_fix_default_track", return_value=ENGLISH) as auto_fix:
        await run(library)
        assert auto_fix.call_args.args[-1] is True
    async with library.sessions() as db:
        response = await media.update_show(show_id, ShowUpdate(is_anime=False), library.user, db)
        assert response.media_type == base_type
        assert response.anime_source == "manual"
        assert response.issues_count == 0
        await db.commit()
    with patch.object(scanning, "PlexConnector") as plex:
        plex.return_value.sync_show_metadata.return_value = {"title": "Plex anime", "is_anime": True}
        await run(library, token="synthetic-test-token")
    async with library.sessions() as db:
        show = await db.get(Show, show_id)
        assert show.media_type == base_type and not show.is_anime
        assert show.anime_source == "manual"


@pytest.mark.asyncio
async def test_overlapping_roots_scan_once_and_use_most_specific_classification(library):
    child = library.root / "Nested"
    source = write_media(child)
    async with library.sessions() as db:
        db.add(ScanLocation(user_id=library.user.id, path=str(child), label="Nested anime", media_type="anime"))
        await db.commit()
    with patch.object(scanning.AudioAnalyzer, "analyze", return_value=ENGLISH) as analyze:
        status = await run(library, roots=[str(library.root), str(child)])
        analyze.assert_called_once_with(str(source))
    assert status.files_total == 1
    async with library.sessions() as db:
        assert (await db.scalar(select(Show))).media_type == "anime"
        assert [location.file_count for location in (await db.scalars(select(ScanLocation))).all()] == [1, 1]
    await run(library)  # Parent-only scan still respects the configured child type.
    async with library.sessions() as db:
        assert (await db.scalar(select(Show))).media_type == "anime"


@pytest.mark.asyncio
async def test_removed_and_moved_files_reconcile_tracks_and_empty_titles(library):
    removed = write_media(library.root, "Removed/Season 01/E01.mkv")
    moved = write_media(library.root, "Moved/Season 01/E01.mkv")
    await run(library)
    removed.unlink()
    destination = write_media(library.root, "Destination/Season 01/E01.mkv")
    moved.replace(destination)
    status = await run(library)
    assert status.files_removed == 2
    assert [record.file_path for record in await files(library)] == [str(destination)]
    async with library.sessions() as db:
        assert await db.scalar(select(func.count(AudioTrack.id))) == 1
        assert await db.scalar(select(func.count(Season.id))) == 1
        assert await db.scalar(select(Show.title)) == "Destination"
        assert (await db.get(ScanLocation, library.location.id)).file_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["probe", "discovery", "cancel", "unmount"])
async def test_partial_failed_and_cancelled_scans_never_reconcile(library, problem):
    missing = write_media(library.root, "Missing/Season 01/E01.mkv")
    write_media(library.root, "Present/Season 01/E01.mkv")
    await run(library)
    missing.unlink()
    async with library.sessions() as db:
        before = (await db.get(ScanLocation, library.location.id)).last_scanned
    if problem == "probe":
        with patch.object(scanning.AudioAnalyzer, "analyze", return_value={"error": "cannot analyze", "audio_tracks": []}):
            status = await run(library)
        assert status.outcome == "completed_with_errors"
    elif problem == "discovery":
        def unreadable(*args, onerror=None, **kwargs):
            yield str(library.root), [], []
            onerror(PermissionError("one directory is unreadable"))
        with patch.object(scanning.os, "walk", side_effect=unreadable):
            status = await run(library)
        assert status.outcome == "failed"
    elif problem == "cancel":
        process = scanning.MediaScanner.process_file
        async def cancel_after_file(self, *args, **kwargs):
            result = await process(self, *args, **kwargs)
            await scan_state_manager.cancel_scan(library.user.id)
            return result
        with patch.object(scanning.MediaScanner, "process_file", new=cancel_after_file):
            status = await run(library)
        assert status.outcome == "cancelled"
    else:
        with patch.object(scanning, "_root_identity", side_effect=[(1, 1), (2, 2)]):
            status = await run(library)
        assert status.outcome == "failed"
    assert status.files_removed == 0
    assert len(await files(library)) == 2
    async with library.sessions() as db:
        assert (await db.get(ScanLocation, library.location.id)).last_scanned == before


@pytest.mark.asyncio
async def test_reconciliation_is_scoped_to_user_and_directory_boundary(library):
    source = write_media(library.root)
    await run(library)
    async with library.sessions() as db:
        other = User(plex_user_id="456", plex_username="other", plex_token="test")
        db.add(other)
        await db.flush()
        db.add_all([
            MediaFile(user_id=other.id, file_path=str(source), filename="same path", file_size=1, last_modified=datetime.now()),
            MediaFile(user_id=library.user.id, file_path=str(library.root) + "-sibling/missing.mkv", filename="outside root", file_size=1, last_modified=datetime.now()),
        ])
        await db.commit()
        other_id = other.id
    source.unlink()
    await run(library)
    assert [record.filename for record in await files(library)] == ["outside root"]
    async with library.sessions() as db:
        assert await db.scalar(select(func.count(MediaFile.id)).where(MediaFile.user_id == other_id)) == 1


@pytest.mark.parametrize("extensions", [[], ["../mkv"], ["*"], ["."], [".mkv/.mp4"]])
def test_invalid_extensions_are_rejected(extensions):
    with pytest.raises(ValueError):
        UserSettingsUpdate(file_extensions=extensions)


def test_conflicting_classification_is_rejected():
    with pytest.raises(ValueError):
        ShowUpdate(media_type="tv", is_anime=True)


@pytest.mark.asyncio
async def test_scan_can_be_cancelled_while_a_native_probe_is_running(library):
    write_media(library.root)
    started, release = Event(), Event()

    def slow_probe(_):
        started.set()
        assert release.wait(timeout=5), "Probe blocked the event loop or cancellation"
        return ENGLISH

    with patch.object(scanning.AudioAnalyzer, "analyze", side_effect=slow_probe):
        task = asyncio.create_task(run(library))
        try:
            assert await asyncio.to_thread(started.wait, 3)
            cancelled = await asyncio.wait_for(scan_state_manager.cancel_scan(library.user.id), timeout=1)
            assert cancelled and cancelled.is_running
        finally:
            release.set()
            result = await task
    assert result.outcome == "cancelled"


@pytest.mark.asyncio
async def test_unreadable_plex_token_still_schedules_a_local_scan(library):
    write_media(library.root)
    background = BackgroundTasks()
    async with library.sessions() as db:
        with patch.object(scan_api, "decrypt_value", side_effect=ValueError("wrong key")):
            response = await scan_api.start_scan(ScanStartRequest(), background, library.user, db)
    assert response.is_running
    assert background.tasks[0].kwargs["user_plex_token"] is None
    await background()
    assert len(await files(library)) == 1
    result = await scan_state_manager.get_status(library.user.id)
    assert not result.is_running
    assert result.warning_count == 1


def test_empty_plex_library_is_loaded_only_once():
    from app.core.plex_connector import PlexConnector
    connector = PlexConnector("synthetic")
    with patch.object(connector, "_get_server") as server:
        server.return_value.library.sections.return_value = []
        assert connector.sync_show_metadata("/media/Show/E01.mkv", "Show") is None
        assert connector.sync_show_metadata("/media/Show/E02.mkv", "Show") is None
        server.return_value.library.sections.assert_called_once()
