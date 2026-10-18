"""Cached policy changes must never read or mutate physical media."""

from datetime import datetime
from unittest.mock import Mock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api import settings as settings_api
from app.core import reevaluation, scanner
from app.core.job_context import current_job
from app.core.policy_revision import evaluation_revision
from app.models.entities import AudioTrack, Job, MediaFile
from app.models.schemas import AudioPreferences

from test_database_migrations import database  # noqa: F401
from test_jobs import queue, enqueue_scan, execute_next  # noqa: F401


@pytest_asyncio.fixture
async def catalog(queue, monkeypatch):
    queue.app.include_router(settings_api.router, prefix="/api/settings")
    monkeypatch.setattr(reevaluation, "async_session_maker", queue.sessions)
    await enqueue_scan(queue)
    await execute_next(queue)
    return queue


async def cached_file(catalog):
    async with catalog.sessions() as db:
        return await db.scalar(select(MediaFile).where(MediaFile.user_id == catalog.user.id).options(selectinload(MediaFile.audio_tracks)))


@pytest.mark.asyncio
async def test_rule_save_reevaluates_cache_without_probes_writes_or_fresh_scan_dates(catalog, monkeypatch):
    before = await cached_file(catalog)
    async with catalog.sessions() as db:
        mf = await db.get(MediaFile, before.id)
        mf.language_review_note = "Retain my review note"
        await db.commit()
    # A missing physical file must not block evaluation of its saved metadata.
    catalog.source.unlink()
    native = Mock(side_effect=AssertionError("Native/media operation during cached evaluation"))
    monkeypatch.setattr(scanner.AudioAnalyzer, "analyze", native)
    monkeypatch.setattr(scanner, "set_default_track_by_index", native)
    response = await catalog.client.put("/api/settings", json={"audio_preferences": {
        "preferred_codecs": ["FLAC"], "auto_fix_english_default_non_anime": True}})
    assert response.status_code == 200
    status = (await catalog.client.get("/api/settings/evaluation")).json()
    assert status["files_pending"] == 1 and status["files_current"] == 0
    assert status["latest_job"]["status"] == "queued"
    result = await execute_next(catalog)
    assert result.status == "completed" and result.result["reevaluated"] == 1
    after = await cached_file(catalog)
    assert {issue.code for issue in after.issue_records} == {"NO_PREFERRED_CODEC"}
    assert after.last_scanned == before.last_scanned and after.last_modified == before.last_modified
    assert after.language_review_note == "Retain my review note"
    assert [(t.id, t.language, t.is_default) for t in after.audio_tracks] == [(t.id, t.language, t.is_default) for t in before.audio_tracks]
    assert after.issue_policy_revision == status["policy_revision"]
    assert (await catalog.client.get("/api/settings/evaluation")).json()["files_current"] == 1
    native.assert_not_called()


@pytest.mark.asyncio
async def test_missing_cache_is_preserved_but_successful_zero_audio_is_evaluated(catalog):
    async with catalog.sessions() as db:
        missing = MediaFile(user_id=catalog.user.id, filename="legacy.mkv", file_path="/not/read/legacy.mkv",
            file_size=1, last_modified=datetime(2026, 1, 1), issue_details="Preserve legacy evidence", has_issues=True)
        empty = MediaFile(user_id=catalog.user.id, filename="silent.mkv", file_path="/not/read/silent.mkv",
            file_size=1, last_modified=datetime(2026, 1, 1), analysis_version=1)
        foreign = MediaFile(user_id=catalog.other.id, filename="foreign.mkv", file_path="/not/read/foreign.mkv",
            file_size=1, last_modified=datetime(2026, 1, 1), analysis_version=1, issue_details="Other catalog")
        db.add_all([missing, empty, foreign])
        await db.commit()
    assert (await catalog.client.post("/api/settings/reevaluate")).status_code == 202
    result = await execute_next(catalog)
    assert result.result["needs_scan"] == 1
    assert result.result["reevaluated"] == 1 and result.result["unchanged"] == 1
    async with catalog.sessions() as db:
        assert (await db.get(MediaFile, missing.id)).issue_details == "Preserve legacy evidence"
        assert {r.code for r in (await db.get(MediaFile, empty.id)).issue_records} == {"NO_AUDIO"}
        assert (await db.get(MediaFile, foreign.id)).issue_details == "Other catalog"
    status = (await catalog.client.get("/api/settings/evaluation")).json()
    assert status["files_total"] == 3 and status["files_current"] == 2 and status["files_needing_scan"] == 1


@pytest.mark.asyncio
async def test_rapid_policy_saves_coalesce_and_running_old_revision_is_superseded(catalog):
    assert (await catalog.client.put("/api/settings", json={"audio_preferences": {"preferred_codecs": ["FLAC"]}})).status_code == 200
    first_id = await catalog.manager.claim()
    for codec in ("AAC", "Opus", "DTS"):
        assert (await catalog.client.put("/api/settings", json={"audio_preferences": {"preferred_codecs": [codec]}})).status_code == 200
    async with catalog.sessions() as db:
        queued = (await db.scalars(select(Job).where(Job.kind == "reevaluate", Job.status == "queued"))).all()
        assert len(queued) == 1 and queued[0].payload["policy"]["preferred_codecs"] == ["dts"]
    await catalog.manager.execute(first_id)
    async with catalog.sessions() as db:
        assert (await db.get(Job, first_id)).status == "superseded"
    assert (await execute_next(catalog)).status == "completed"
    assert await catalog.manager.claim() is None
    assert (await catalog.client.get("/api/settings/evaluation")).json()["files_current"] == 1


@pytest.mark.asyncio
async def test_non_evaluation_preferences_do_not_create_work(catalog):
    original = (await catalog.client.get("/api/settings/evaluation")).json()["policy_revision"]
    response = await catalog.client.put("/api/settings", json={"audio_preferences": {
        "auto_fix_english_default_non_anime": True, "audio_track_keep_languages": ["ja"]}, "file_extensions": [".mp4"]})
    assert response.status_code == 200
    assert (await catalog.client.get("/api/settings/evaluation")).json()["policy_revision"] == original
    assert await catalog.manager.claim() is None
    assert evaluation_revision(AudioPreferences(preferred_codecs=["AAC", "FLAC"])) == evaluation_revision(AudioPreferences(preferred_codecs=["flac", "aac", "aac"]))


@pytest.mark.asyncio
async def test_cancelled_batches_can_be_retried_without_repeating_current_records(catalog, monkeypatch):
    async with catalog.sessions() as db:
        db.add(MediaFile(user_id=catalog.user.id, filename="second.mkv", file_path="/not/read/second.mkv",
            file_size=1, last_modified=datetime(2026, 1, 1), analysis_version=1))
        await db.commit()
    await catalog.client.put("/api/settings", json={"audio_preferences": {"preferred_codecs": ["FLAC"]}})
    monkeypatch.setattr(reevaluation, "BATCH_SIZE", 1)
    save = catalog.manager.save_progress

    async def cancel_after_first_batch(progress, **kwargs):
        await save(progress, **kwargs)
        if progress["files_scanned"] == 1:
            current_job.get().cancelled.set()
    monkeypatch.setattr(catalog.manager, "save_progress", cancel_after_first_batch)
    cancelled = await execute_next(catalog)
    assert cancelled.status == "cancelled" and cancelled.progress["files_scanned"] == 1
    monkeypatch.setattr(catalog.manager, "save_progress", save)
    await catalog.client.post("/api/settings/reevaluate")
    completed = await execute_next(catalog)
    assert completed.result["reevaluated"] == 1 and completed.result["unchanged"] == 1


@pytest.mark.asyncio
async def test_settings_and_queued_work_are_atomic_when_queue_is_full(catalog):
    async with catalog.sessions() as db:
        db.add_all([Job(user_id=catalog.user.id, kind="rescan_file", payload={}) for _ in range(100)])
        await db.commit()
    failed = await catalog.client.put("/api/settings", json={"audio_preferences": {"preferred_codecs": ["FLAC"]}})
    assert failed.status_code == 429
    settings = (await catalog.client.get("/api/settings")).json()
    assert settings["audio_preferences"]["preferred_codecs"] == []


@pytest.mark.asyncio
async def test_reset_preferences_queues_new_revision_and_status_is_owned(catalog):
    await catalog.client.put("/api/settings", json={"audio_preferences": {"preferred_codecs": ["FLAC"]}})
    await execute_next(catalog)
    assert (await cached_file(catalog)).has_issues
    assert (await catalog.client.delete("/api/settings")).status_code == 200
    await execute_next(catalog)
    assert not (await cached_file(catalog)).has_issues
    from app.api.auth import get_current_user
    catalog.app.dependency_overrides[get_current_user] = lambda: catalog.other
    status = (await catalog.client.get("/api/settings/evaluation")).json()
    assert status["files_total"] == 0 and status["latest_job"] is None


@pytest.mark.asyncio
async def test_incremental_scan_reprobes_missing_analysis_but_not_current_metadata(catalog, monkeypatch):
    before = await cached_file(catalog)
    async with catalog.sessions() as db:
        (await db.get(MediaFile, before.id)).analysis_version = None
        await db.commit()
    native = Mock(return_value={"container": "Matroska", "audio_tracks": [{"index": 0, "language": "en", "is_default": True}]})
    monkeypatch.setattr(scanner.AudioAnalyzer, "analyze", native)
    await enqueue_scan(catalog)
    assert (await execute_next(catalog)).status == "completed"
    assert (await cached_file(catalog)).analysis_version == 1
    native.assert_called_once()
    await enqueue_scan(catalog)
    await execute_next(catalog)
    native.assert_called_once()


@pytest.mark.asyncio
async def test_interrupted_reevaluation_keeps_pending_status_and_can_be_retried(catalog):
    await catalog.client.put("/api/settings", json={"audio_preferences": {"preferred_codecs": ["FLAC"]}})
    job_id = await catalog.manager.claim()
    await catalog.manager.recover()
    status = (await catalog.client.get("/api/settings/evaluation")).json()
    assert status["latest_job"]["id"] == job_id and status["latest_job"]["status"] == "interrupted"
    assert status["files_pending"] == 1
    await catalog.client.post("/api/settings/reevaluate")
    assert (await execute_next(catalog)).status == "completed"
    assert (await catalog.client.get("/api/settings/evaluation")).json()["files_pending"] == 0


@pytest.mark.asyncio
async def test_sqlite_snapshot_retry_does_not_apply_a_superseded_policy(catalog):
    import sqlite3
    from sqlalchemy import event
    engine = catalog.sessions.kw["bind"]
    if engine.dialect.name != "sqlite":
        pytest.skip("SQLite-specific independent writer snapshot conflict")
    await catalog.client.put("/api/settings", json={"audio_preferences": {"preferred_codecs": ["FLAC"]}})
    writes = []

    def competing_write(_connection, _cursor, statement, *_):
        if not writes and statement.startswith("UPDATE media_files"):
            with sqlite3.connect(engine.url.database) as writer:
                writer.execute("UPDATE user_preferences SET value=? WHERE user_id=? AND key='audio_preferences'",
                               ('{"preferred_codecs":["Opus"]}', catalog.user.id))
            writes.append(True)
    event.listen(engine.sync_engine, "before_cursor_execute", competing_write)
    try:
        result = await execute_next(catalog)
        assert result.status == "superseded" and writes == [True]
        assert result.result["reevaluated"] == 0
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", competing_write)
    await catalog.client.post("/api/settings/reevaluate")
    assert (await execute_next(catalog)).status == "completed"
