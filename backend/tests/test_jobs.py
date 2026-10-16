"""Exercise the durable queue on both supported database engines."""

import asyncio
import shutil
import subprocess
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api import jobs as jobs_api, media, scan
from app.api.auth import get_current_user
from app.core import jobs, scanner
from app.core.scan_state import scan_state_manager
from app.core.worker_lock import WorkerLock
from app.core import media_access
from app.config import get_settings
from app.models.database import get_db
from app.models.entities import Base, Job, MediaFile, ScanLocation, Show, User
from app.models.schemas import ScanStartRequest, MediaEditCapabilities
from fastapi import BackgroundTasks

# Reuse the isolated SQLite/PostgreSQL integration database fixture used by migrations.
from test_database_migrations import database  # noqa: F401

REAL_ANALYZE = scanner.AudioAnalyzer.analyze


@pytest_asyncio.fixture
async def queue(database, tmp_path, monkeypatch):
    async with database.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(database, expire_on_commit=False)
    manager = jobs.JobManager()
    for module in (jobs, jobs_api, media, scan):
        monkeypatch.setattr(module, "job_manager", manager)
    monkeypatch.setattr(jobs, "async_session_maker", sessions)
    monkeypatch.setattr(scanner, "async_session_maker", sessions)
    monkeypatch.setattr(scanner.AudioAnalyzer, "analyze", lambda *_: {
        "container": "Matroska", "audio_tracks": [{"index": 0, "language": "en", "is_default": True}]})
    root = tmp_path / "media"
    root.mkdir()
    source = root / "movie.mkv"
    source.write_bytes(b"Disposable media; native parsing is mocked.")
    async with sessions() as db:
        user, other = User(plex_username="owner"), User(plex_username="other")
        db.add_all([user, other])
        await db.flush()
        location = ScanLocation(user_id=user.id, path=str(root), label="Movies", media_type="movie")
        db.add(location)
        await db.commit()
    app = FastAPI()
    app.include_router(jobs_api.router, prefix="/api/jobs")
    app.include_router(scan.router, prefix="/api/scan")
    app.include_router(media.router, prefix="/api/media")

    async def session_dependency():
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    app.dependency_overrides[get_db] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: user
    await scan_state_manager.reset()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        yield SimpleNamespace(manager=manager, sessions=sessions, user=user, other=other,
                              location=location, source=source, app=app, client=client)
    if manager.task:
        await manager.stop()
    await scan_state_manager.reset()


async def enqueue_scan(queue):
    async with queue.sessions() as db:
        return await scan.start_scan(ScanStartRequest(), BackgroundTasks(), queue.user, db)


async def execute_next(queue):
    job_id = await queue.manager.claim()
    assert job_id
    await queue.manager.execute(job_id)
    async with queue.sessions() as db:
        return await db.get(Job, job_id)


@pytest.mark.asyncio
async def test_scan_progress_and_outcome_survive_state_reset(queue):
    started = await enqueue_scan(queue)
    assert started.job_status == "queued"
    with pytest.raises(HTTPException) as duplicate:
        await enqueue_scan(queue)
    assert duplicate.value.status_code == 409
    result = await execute_next(queue)
    assert result.status == "completed"
    assert result.progress["files_scanned"] == 1
    assert result.progress["outcome"] == "completed"
    assert result.active_key is None
    await scan_state_manager.reset()
    status = (await queue.client.get("/api/scan/status")).json()
    assert not status["is_running"]
    assert status["files_scanned"] == 1
    assert status["outcome"] == "completed"
    assert status["job_id"] == result.id


@pytest.mark.asyncio
async def test_restart_preserves_queued_work_but_never_replays_running_edits(queue):
    queued = await enqueue_scan(queue)
    async with queue.sessions() as db:
        edit = Job(user_id=queue.user.id, kind="remove_audio", status="running", active_key="file:1:4",
                   payload={"file_id": 4}, progress={"files_scanned": 0})
        db.add(edit)
        await db.commit()
    await jobs.JobManager().recover()
    async with queue.sessions() as db:
        assert (await db.get(Job, queued.job_id)).status == "queued"
        interrupted = await db.get(Job, edit.id)
        assert interrupted.status == "interrupted"
        assert "not retried" in interrupted.error
        assert interrupted.finished_at and interrupted.active_key is None
    assert (await execute_next(queue)).id == queued.job_id
    assert await queue.manager.claim() is None


@pytest.mark.asyncio
async def test_owned_job_reads_cancel_and_mutation_coordination(queue):
    started = await enqueue_scan(queue)
    assert (await queue.client.delete("/api/media/files")).status_code == 409
    assert (await queue.client.patch(f"/api/scan/locations/{queue.location.id}", json={"enabled": False})).status_code == 409
    assert (await queue.client.delete(f"/api/scan/locations/{queue.location.id}")).status_code == 409
    assert (await queue.client.get("/api/jobs")).json()["total"] == 1
    queue.app.dependency_overrides[get_current_user] = lambda: queue.other
    assert (await queue.client.get(f"/api/jobs/{started.job_id}")).status_code == 404
    assert (await queue.client.post(f"/api/jobs/{started.job_id}/cancel")).status_code == 404
    assert (await queue.client.get("/api/jobs")).json()["items"] == []
    # Another user's idle catalog is independent.
    assert (await queue.client.delete("/api/media/files")).status_code == 200
    queue.app.dependency_overrides[get_current_user] = lambda: queue.user
    cancelled = await queue.client.post(f"/api/jobs/{started.job_id}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    assert await queue.manager.claim() is None
    assert (await queue.client.delete("/api/media/files")).status_code == 200
    assert (await queue.client.delete(f"/api/scan/locations/{queue.location.id}")).status_code == 204


@pytest.mark.asyncio
async def test_rescan_http_returns_before_execution_and_retains_outcome(queue, monkeypatch):
    await enqueue_scan(queue)
    await execute_next(queue)
    async with queue.sessions() as db:
        mf = await db.scalar(select(MediaFile))
        file_id = mf.id
    rescan = AsyncMock(wraps=media.rescan_media_file)
    monkeypatch.setattr(media, "rescan_media_file", rescan)
    response = await queue.client.post(f"/api/media/files/{file_id}/rescan")
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    rescan.assert_not_awaited()
    assert (await queue.client.post(f"/api/media/files/{file_id}/rescan")).status_code == 409
    job = await execute_next(queue)
    assert job.status == "completed"
    assert job.result["succeeded"] == 1
    rescan.assert_awaited_once()
    # POST ownership is checked before a job is created.
    queue.app.dependency_overrides[get_current_user] = lambda: queue.other
    assert (await queue.client.post(f"/api/media/files/{file_id}/rescan")).status_code == 404


@pytest.mark.asyncio
async def test_title_rescan_commits_each_file_and_continues_after_a_probe_failure(queue, monkeypatch):
    await enqueue_scan(queue)
    await execute_next(queue)
    async with queue.sessions() as db:
        mf = await db.scalar(select(MediaFile))
        show_id = mf.show_id
        db.add(MediaFile(user_id=queue.user.id, show_id=show_id, filename="missing.mkv",
                         file_path=str(queue.source.parent / "missing.mkv"), file_size=1, last_modified=datetime(2026, 1, 1)))
        await db.commit()
    response = await queue.client.post(f"/api/media/shows/{show_id}/rescan")
    assert response.status_code == 202
    result = await execute_next(queue)
    assert result.status == "completed_with_errors"
    assert result.result["succeeded"] == 1 and result.result["failed"] == 1
    assert result.progress["files_scanned"] == 2
    assert len(result.progress["errors"]) == 1


@pytest.mark.asyncio
async def test_running_edit_cannot_be_cancelled_and_is_never_retried(queue, monkeypatch):
    async with queue.sessions() as db:
        job = await queue.manager.enqueue(db, queue.user.id, "default_audio", {"file_id": 999, "request": {"language": "en"}})
    assert await queue.manager.claim() == job.id
    assert (await queue.client.post(f"/api/jobs/{job.id}/cancel")).status_code == 409
    await queue.manager.execute(job.id)  # Missing file is a terminal failure, not an automatic retry.
    assert await queue.manager.claim() is None
    response = await queue.client.get(f"/api/jobs/{job.id}")
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == "Media file not found"


@pytest.mark.asyncio
async def test_queue_bound_and_finished_retention(queue, monkeypatch):
    async with queue.sessions() as db:
        db.add_all([Job(user_id=queue.user.id, kind="rescan_file", status="completed", payload={}) for _ in range(205)])
        await db.commit()
        await queue.manager.enqueue(db, queue.user.id, "rescan_file", {"file_id": 999})
    await execute_next(queue)
    async with queue.sessions() as db:
        assert await db.scalar(select(func.count(Job.id))) == jobs.HISTORY_LIMIT
        db.add_all([Job(user_id=queue.user.id, kind="rescan_file", payload={}) for _ in range(100)])
        await db.commit()
        with pytest.raises(HTTPException) as full:
            await queue.manager.enqueue(db, queue.user.id, "rescan_file", {"file_id": 999})
        assert full.value.status_code == 429


@pytest.mark.asyncio
async def test_worker_starts_with_queued_work_and_stops_cleanly(queue):
    started = await enqueue_scan(queue)
    await queue.manager.start()
    for _ in range(100):
        async with queue.sessions() as db:
            row = await db.get(Job, started.job_id)
            if row.status not in jobs.ACTIVE:
                break
        await asyncio.sleep(0.05)
    assert row.status == "completed"
    await queue.manager.stop()
    assert queue.manager.task is None


@pytest.mark.asyncio
async def test_second_application_worker_is_rejected_before_recovery(queue):
    async with queue.sessions() as db:
        engine = db.bind
    first, second = WorkerLock(engine), WorkerLock(engine)
    await first.acquire()
    try:
        with pytest.raises(RuntimeError, match="one application process"):
            await second.acquire()
    finally:
        await first.release()
    await second.acquire()
    await second.release()


@pytest.mark.asyncio
async def test_running_scan_cancellation_finishes_and_releases_reservation(queue, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    async def wait_for_cancel(*args, **kwargs):
        started.set()
        await release.wait()
        await scan_state_manager.update_status(queue.user.id, is_running=True, outcome="running")
        await scan_state_manager.finish_scan(queue.user.id)
    monkeypatch.setattr(scanner, "run_scan", wait_for_cancel)
    job = await enqueue_scan(queue)
    assert await queue.manager.claim() == job.job_id
    task = asyncio.create_task(queue.manager.execute(job.job_id))
    try:
        await asyncio.wait_for(started.wait(), 3)
        response = await queue.client.post(f"/api/jobs/{job.job_id}/cancel")
        assert response.json()["status"] == "running"
        assert response.json()["cancel_requested"]
    finally:
        release.set()
        await task
    result = (await queue.client.get(f"/api/jobs/{job.job_id}")).json()
    assert result["status"] == "cancelled"
    assert (await enqueue_scan(queue)).job_status == "queued"


@pytest.mark.asyncio
async def test_edit_rechecks_write_gate_at_execution_and_keeps_stale_selection(queue, monkeypatch):
    await enqueue_scan(queue)
    await execute_next(queue)
    async with queue.sessions() as db:
        mf = await db.scalar(select(MediaFile))
        file_id = mf.id
        stamp = mf.last_scanned.isoformat()
    # Queueing cannot bypass the write gate.
    disabled = await queue.client.post(f"/api/media/files/{file_id}/default-audio", json={"track_index": 0, "expected_last_scanned": stamp})
    assert disabled.status_code == 403
    # Admit under an enabled gate, then disable it before the worker executes.
    with monkeypatch.context() as enabled:
        enabled.setattr(media, "get_media_edit_capabilities", lambda *_: MediaEditCapabilities(set_default_audio=True, remove_audio_tracks=True))
        response = await queue.client.post(f"/api/media/files/{file_id}/default-audio", json={"track_index": 0, "expected_last_scanned": stamp})
    assert response.status_code == 202
    native = AsyncMock()
    monkeypatch.setattr(media, "set_default_track_by_index", native)
    result = await execute_next(queue)
    assert result.status == "failed"
    assert "disabled" in result.error
    native.assert_not_called()
    # Queue a reviewed selection, then invalidate its metadata before execution.
    monkeypatch.setattr(media, "_require_editable_current_file", lambda *_: None)
    monkeypatch.setattr(media, "get_media_edit_capabilities", lambda *_: MediaEditCapabilities(set_default_audio=True, remove_audio_tracks=True))
    response = await queue.client.post(f"/api/media/files/{file_id}/default-audio", json={"track_index": 0, "expected_last_scanned": stamp})
    async with queue.sessions() as db:
        mf = await db.get(MediaFile, file_id)
        mf.last_scanned = datetime(2027, 1, 1)
        await db.commit()
    result = await execute_next(queue)
    assert result.status == "failed" and "out of date" in result.error.lower()
    native.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.skipif(any(shutil.which(tool) is None for tool in ("ffmpeg", "mkvmerge", "mkvpropedit")), reason="requires native media tools")
async def test_real_queued_edits_verify_flags_and_preserve_backup(queue, monkeypatch):
    monkeypatch.setattr(scanner.AudioAnalyzer, "analyze", REAL_ANALYZE)
    monkeypatch.setattr(media_access, "MEDIA_ROOT", queue.source.parent)
    monkeypatch.setattr(get_settings(), "media_writes_enabled", True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
        "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-map", "0:a", "-map", "1:a", "-t", "0.2",
        "-c:a", "pcm_s16le", "-metadata:s:a:0", "language=eng", "-metadata:s:a:1", "language=jpn",
        "-disposition:a:0", "default", "-disposition:a:1", "0", str(queue.source)],
        check=True, capture_output=True, timeout=30)
    await enqueue_scan(queue)
    assert (await execute_next(queue)).status == "completed"
    async with queue.sessions() as db:
        mf = await db.scalar(select(MediaFile))
        file_id, stamp = mf.id, mf.last_scanned.isoformat()
    response = await queue.client.post(f"/api/media/files/{file_id}/default-audio",
        json={"track_index": 1, "expected_last_scanned": stamp})
    assert response.status_code == 202
    assert (await execute_next(queue)).status == "completed"
    tracks = REAL_ANALYZE(scanner.AudioAnalyzer(), str(queue.source))["audio_tracks"]
    assert [track["index"] for track in tracks if track["is_default"]] == [1]
    original = queue.source.read_bytes()
    async with queue.sessions() as db:
        stamp = (await db.get(MediaFile, file_id)).last_scanned.isoformat()
    plan = (await queue.client.get(f"/api/media/files/{file_id}/audio-tracks/plan", params={"keep_track_indices": 0})).json()
    response = await queue.client.post(f"/api/media/files/{file_id}/audio-tracks/remove",
        json={"keep_track_indices": [0], "expected_last_scanned": stamp, "keep_backup": True,
              "expected_policy_revision": plan["policy_revision"], "acknowledge_policy_warnings": True})
    assert response.status_code == 202
    result = await execute_next(queue)
    assert result.status == "completed"
    assert result.result["removed_track_indices"] == [1]
    assert queue.source.with_suffix(".mkv.bak").read_bytes() == original
    assert result.result["backup_path"] == str(queue.source.with_suffix(".mkv.bak"))
    assert [track["language"] for track in REAL_ANALYZE(scanner.AudioAnalyzer(), str(queue.source))["audio_tracks"]] == ["en"]


@pytest.mark.asyncio
async def test_queue_admission_during_probe_does_not_poison_rescan_snapshot(queue, monkeypatch):
    await enqueue_scan(queue)
    await execute_next(queue)
    async with queue.sessions() as db:
        mf = await db.scalar(select(MediaFile))
        file_id = mf.id
    # Admit another job while analysis is genuinely in flight in a thread.
    from threading import Event
    started_probe, finish_probe = Event(), Event()

    def slow_probe(*_):
        started_probe.set()
        assert finish_probe.wait(timeout=5)
        return {"container": "Matroska", "audio_tracks": [{"index": 0, "language": "en", "is_default": True}]}
    monkeypatch.setattr(scanner.AudioAnalyzer, "analyze", slow_probe)
    response = await queue.client.post(f"/api/media/files/{file_id}/rescan")
    job_id = await queue.manager.claim()
    task = asyncio.create_task(queue.manager.execute(job_id))
    try:
        assert await asyncio.to_thread(started_probe.wait, 3)
        assert (await enqueue_scan(queue)).is_running
    finally:
        finish_probe.set()
        await task
    result = (await queue.client.get(f"/api/jobs/{job_id}")).json()
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_history_uses_finish_order_and_lists_running_work_before_newer_queued_work(queue):
    async with queue.sessions() as db:
        # An old queued job finishing now must not be evicted by newer job IDs.
        old = Job(user_id=queue.user.id, kind="rescan_file", payload={"file_id": 999})
        db.add(old)
        await db.commit()
        db.add_all([Job(user_id=queue.user.id, kind="rescan_file", status="completed",
                       finished_at=datetime(2026, 1, 1), payload={}) for _ in range(200)])
        await db.commit()
        await queue.manager.cancel(db, old)
        assert (await db.get(Job, old.id)).status == "cancelled"
        assert await db.scalar(select(func.count(Job.id))) == 200
        first = await queue.manager.enqueue(db, queue.user.id, "rescan_file", {"file_id": 1})
        second = await queue.manager.enqueue(db, queue.user.id, "rescan_file", {"file_id": 2})
    assert await queue.manager.claim() == first.id
    page = (await queue.client.get("/api/jobs", params={"limit": 1})).json()
    assert page["items"][0]["id"] == first.id
    assert page["latest_finished_at"]


@pytest.mark.asyncio
async def test_shutdown_cancellation_does_not_abandon_a_running_write(queue, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_write(*_):
        from app.core.job_context import current_job
        started.set()
        await release.wait()
        assert not current_job.get().cancelled.is_set()
        return {"message": "Verified edit"}, "completed"
    monkeypatch.setattr(queue.manager, "execute_media", slow_write)
    async with queue.sessions() as db:
        job = await queue.manager.enqueue(db, queue.user.id, "default_audio", {"file_id": 1})
    await queue.manager.claim()
    queue.manager.task = asyncio.create_task(queue.manager.execute(job.id))
    await asyncio.wait_for(started.wait(), 3)
    stop = asyncio.create_task(queue.manager.stop())
    try:
        await asyncio.sleep(0)
        stop.cancel()
        await asyncio.sleep(0)
        assert not stop.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await stop
    async with queue.sessions() as db:
        assert (await db.get(Job, job.id)).status == "completed"
    assert queue.manager.task is None
