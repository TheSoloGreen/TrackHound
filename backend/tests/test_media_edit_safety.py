"""Failure cases must not mutate media or discard a successful prior analysis."""

from datetime import datetime
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.api import media
from app.config import get_settings
from app.core import media_access
from app.core.scan_state import scan_state_manager
from app.core.scanner import MediaScanner
from app.core.audio_fixer import AudioTrackRemovalResult
from app.models.entities import Base, User, MediaFile, AudioTrack, UserPreference
from app.models.schemas import AudioTrackRemovalRequest, UpdateDefaultAudioRequest


@pytest_asyncio.fixture
async def scanned_file(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"synthetic media; probes are mocked")
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        user = User(plex_user_id="123", plex_username="user", plex_token="test")
        db.add(user)
        await db.flush()
        mf = MediaFile(user_id=user.id, file_path=str(source), filename=source.name,
                       file_size=source.stat().st_size, last_modified=datetime.fromtimestamp(source.stat().st_mtime),
                       container_format="Matroska", duration_ms=1000, has_issues=False)
        db.add(mf)
        await db.flush()
        db.add_all([
            AudioTrack(media_file_id=mf.id, track_index=0, language="en", language_raw="eng", is_default=True),
            AudioTrack(media_file_id=mf.id, track_index=1, language="ja", language_raw="jpn"),
            AudioTrack(media_file_id=mf.id, track_index=2, language=None, language_raw="und"),
        ])
        await db.commit()
        mf = (await db.execute(select(MediaFile).options(selectinload(MediaFile.audio_tracks), selectinload(MediaFile.show)))).scalar_one()
        yield db, user, mf, source
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", [{"error": "probe failed"}, {"warning": "analysis unavailable"}])
async def test_failed_refresh_preserves_all_previous_metadata(scanned_file, problem):
    db, user, mf, source = scanned_file
    before = (mf.last_scanned, mf.container_format, mf.duration_ms, mf.has_issues)
    with patch.object(media.AudioAnalyzer, "analyze", return_value={"audio_tracks": [], **problem}):
        with pytest.raises(HTTPException) as exc:
            await media._refresh_media_file_analysis(db, mf, user)
    assert exc.value.status_code == 409
    await db.refresh(mf, attribute_names=["audio_tracks"])
    assert [track.language for track in mf.audio_tracks] == ["en", "ja", None]
    assert (mf.last_scanned, mf.container_format, mf.duration_ms, mf.has_issues) == before


@pytest.mark.asyncio
async def test_background_scan_reports_failed_probe_without_overwriting(scanned_file):
    db, user, mf, source = scanned_file
    source.write_bytes(source.read_bytes() + b"changed")
    scanner = MediaScanner()
    await scan_state_manager.reset()
    with patch.object(scanner.analyzer, "analyze", return_value={"audio_tracks": [], "error": "probe failed"}):
        assert await scanner.process_file(str(source), str(source.parent), "movie", user.id, db) is None
    assert "probe failed" in (await scan_state_manager.get_status(user.id)).errors[0]
    await db.refresh(mf, attribute_names=["audio_tracks"])
    assert len(mf.audio_tracks) == 3
    await scan_state_manager.reset()


@pytest.mark.asyncio
async def test_successful_refresh_updates_file_size_and_modified_time(scanned_file):
    db, user, mf, source = scanned_file
    source.write_bytes(b"changed contents")
    with patch.object(media.AudioAnalyzer, "analyze", return_value={"audio_tracks": [], "container": "Matroska"}):
        await media._refresh_media_file_analysis(db, mf, user)
    assert mf.file_size == source.stat().st_size
    assert mf.last_modified == datetime.fromtimestamp(source.stat().st_mtime)


@pytest.mark.asyncio
@pytest.mark.parametrize("languages,indices", [(["ja"], [1]), (["en", "und"], [0, 2]), (["jpn", "eng"], [0, 1])])
async def test_removal_plan_uses_saved_languages(scanned_file, languages, indices):
    import json
    db, user, mf, _ = scanned_file
    db.add(UserPreference(user_id=user.id, key="audio_preferences", value=json.dumps({"audio_track_keep_languages": languages})))
    await db.flush()
    plan = await media.plan_media_file_audio_tracks(mf.id, user, db)
    assert plan.keep_track_indices == indices
    assert plan.last_scanned == mf.last_scanned
    other = User(id=999, plex_user_id="456", plex_username="other", plex_token="test")
    with pytest.raises(HTTPException) as exc:
        await media.plan_media_file_audio_tracks(mf.id, other, db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_disabled_writes_are_enforced_on_api(scanned_file, monkeypatch):
    db, user, mf, _ = scanned_file
    monkeypatch.setattr(get_settings(), "media_writes_enabled", False)
    with patch.object(media, "remove_unwanted_audio_tracks") as remove:
        with pytest.raises(HTTPException) as exc:
            await media.remove_media_file_audio_tracks(mf.id, AudioTrackRemovalRequest(keep_languages=["en"]), user, db)
    assert exc.value.status_code == 403
    remove.assert_not_called()


@pytest.mark.asyncio
async def test_changed_file_and_stale_selection_cannot_be_edited(scanned_file, monkeypatch):
    db, user, mf, source = scanned_file
    monkeypatch.setattr(get_settings(), "media_writes_enabled", True)
    monkeypatch.setattr(media_access, "MEDIA_ROOT", source.parent)
    monkeypatch.setattr(media_access.shutil, "which", lambda _: "/tool")
    with patch.object(media, "remove_unwanted_audio_tracks") as remove:
        with pytest.raises(HTTPException) as exc:
            await media.remove_media_file_audio_tracks(mf.id, AudioTrackRemovalRequest(keep_track_indices=[0], expected_last_scanned=datetime(2000, 1, 1)), user, db)
        assert exc.value.status_code == 409
        source.write_bytes(b"replaced")
        with pytest.raises(HTTPException) as exc:
            await media.remove_media_file_audio_tracks(mf.id, AudioTrackRemovalRequest(keep_languages=["en"]), user, db)
        assert exc.value.status_code == 409
    remove.assert_not_called()


@pytest.mark.asyncio
async def test_removal_accepts_current_selection_and_refreshes_metadata(scanned_file, monkeypatch):
    db, user, mf, source = scanned_file
    monkeypatch.setattr(get_settings(), "media_writes_enabled", True)
    monkeypatch.setattr(media_access, "MEDIA_ROOT", source.parent)
    monkeypatch.setattr(media_access.shutil, "which", lambda _: "/tool")
    plan = await media.plan_media_file_audio_tracks(mf.id, user, db)

    def remove(path, tracks, *, keep_track_indices, keep_backup):
        assert keep_track_indices == plan.keep_track_indices == [0, 2]
        assert keep_backup
        source.with_suffix(".mkv.bak").write_bytes(source.read_bytes())
        source.write_bytes(b"remuxed")
        return AudioTrackRemovalResult([0, 2], [1], str(source.with_suffix(".mkv.bak")))

    analysis = {"container": "Matroska", "audio_tracks": [
        {"index": 0, "language": "en", "is_default": True},
        {"index": 1, "language_raw": "und"},
    ]}
    with patch.object(media, "remove_unwanted_audio_tracks", side_effect=remove), patch.object(media.AudioAnalyzer, "analyze", return_value=analysis):
        response = await media.remove_media_file_audio_tracks(
            mf.id, AudioTrackRemovalRequest(keep_track_indices=plan.keep_track_indices, expected_last_scanned=plan.last_scanned), user, db
        )
    assert response.removed_track_indices == [1]
    assert [track.language for track in response.media_file.audio_tracks] == ["en", None]
    assert response.media_file.file_size == len(b"remuxed")
    assert response.media_file.last_scanned.replace(tzinfo=None) > plan.last_scanned.replace(tzinfo=None)
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["default", "remove"])
async def test_post_edit_analysis_failure_explains_that_media_was_changed(scanned_file, monkeypatch, operation):
    db, user, mf, source = scanned_file
    monkeypatch.setattr(get_settings(), "media_writes_enabled", True)
    monkeypatch.setattr(media_access, "MEDIA_ROOT", source.parent)
    monkeypatch.setattr(media_access.shutil, "which", lambda _: "/tool")
    backup = str(source.with_suffix(".mkv.bak"))
    with (
        patch.object(media, "set_default_track_by_language", return_value=True),
        patch.object(media, "remove_unwanted_audio_tracks", return_value=AudioTrackRemovalResult([0], [1, 2], backup)),
        patch.object(media.AudioAnalyzer, "analyze", return_value={"audio_tracks": [], "error": "probe failed"}),
    ):
        with pytest.raises(HTTPException) as exc:
            if operation == "default":
                await media.update_media_file_default_audio(mf.id, UpdateDefaultAudioRequest(language="en"), user, db)
            else:
                await media.remove_media_file_audio_tracks(mf.id, AudioTrackRemovalRequest(keep_languages=["en"]), user, db)
    assert exc.value.status_code == 409
    assert ("Default audio was updated" if operation == "default" else "Audio tracks were removed") in exc.value.detail
    assert "Rescan before editing again" in exc.value.detail
    if operation == "remove":
        assert backup in exc.value.detail
    await db.refresh(mf, attribute_names=["audio_tracks"])
    assert len(mf.audio_tracks) == 3


def test_edit_capabilities_reject_read_only_and_escaping_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "media_writes_enabled", True)
    monkeypatch.setattr(media_access, "MEDIA_ROOT", tmp_path / "media")
    monkeypatch.setattr(media_access.shutil, "which", lambda _: "/tool")
    root = tmp_path / "media"
    root.mkdir()
    source = root / "test.mkv"
    source.write_bytes(b"test")
    assert media_access.get_media_edit_capabilities(str(source)).remove_audio_tracks
    with patch.object(media_access.os, "access", return_value=False):
        assert not media_access.get_media_edit_capabilities(str(source)).set_default_audio
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"test")
    link = root / "link.mkv"
    link.symlink_to(outside)
    assert not media_access.get_media_edit_capabilities(str(link)).remove_audio_tracks
    monkeypatch.setattr(media_access.shutil, "which", lambda _: None)
    assert not media_access.get_media_edit_capabilities(str(source)).set_default_audio


def test_scanner_does_not_discover_in_progress_remux_outputs(tmp_path):
    (tmp_path / "movie.mkv").write_bytes(b"test")
    (tmp_path / ".trackhound-temporary.mkv").write_bytes(b"test")
    assert MediaScanner().discover_files(str(tmp_path)) == [str(tmp_path / "movie.mkv")]
