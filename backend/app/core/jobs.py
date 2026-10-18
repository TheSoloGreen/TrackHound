"""Database-backed FIFO queue for the supported single-process installation.

Only this worker invokes media operations. Request handlers admit work under
the same lock used by catalog resets/location changes. Native writes finish
before shutdown; interrupted jobs are reported, never automatically replayed.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import time

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.job_context import JobExecution, current_job
from app.models.database import async_session_maker
from app.models.entities import Job, MediaFile, ScanLocation, Show, User
from app.models.schemas import ScanStatus

logger = logging.getLogger(__name__)
ACTIVE = ("queued", "running")
EDITS = ("default_audio", "remove_audio")
HISTORY_LIMIT = 200


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class JobManager:
    def __init__(self):
        self.coordination = asyncio.Lock()
        self.wake = asyncio.Event()
        self.stopping = False
        self.task = None
        self.execution = None
        self.worker_lock = None

    async def enqueue(self, db, user_id, kind, payload):
        async with self.coordination:
            return await self.enqueue_locked(db, user_id, kind, payload)

    async def enqueue_locked(self, db, user_id, kind, payload):
        """Caller holds coordination; commit pending preferences and work together."""
        if kind == "reevaluate":
            pending = await db.scalar(select(Job).where(Job.user_id == user_id, Job.kind == kind, Job.status == "queued"))
            if pending:
                pending.payload = payload  # Coalesce rapid saves into the newest policy.
                await db.commit()
                self.wake.set()
                return pending
        count = await db.scalar(select(func.count(Job.id)).where(Job.user_id == user_id, Job.status.in_(ACTIVE)))
        if count >= 100:
            raise HTTPException(429, "The work queue is full. Wait for existing jobs to finish.")
        job = Job(user_id=user_id, kind=kind, payload=payload,
                  active_key=f"{kind}:{user_id}" if kind in ("scan", "reevaluate") else
                             f"file:{user_id}:{payload['file_id']}" if "file_id" in payload else
                             f"show:{user_id}:{payload['show_id']}")
        db.add(job)
        try:
            await db.commit()  # Durable before acknowledging the request or waking the worker.
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(409, "A job for this target is already queued or running.") from exc
        self.wake.set()
        return job

    @asynccontextmanager
    async def catalog_mutation(self, db, user_id):
        """Hold admission until the catalog mutation has committed."""
        async with self.coordination:
            active = await db.scalar(select(Job.id).where(Job.user_id == user_id, Job.status.in_(ACTIVE)).limit(1))
            if active:
                raise HTTPException(409, "Queued or running jobs must finish or be cancelled before changing locations or resetting the catalog.")
            yield
            await db.commit()

    async def recover(self):
        async with async_session_maker() as db:
            await db.execute(update(Job).where(Job.status == "running").values(
                status="interrupted", active_key=None, finished_at=utcnow(),
                error="The application stopped during this job. It was not retried. Rescan affected files before reviewing or retrying an edit; preserve any backup files."))
            await db.commit()

    async def start(self, engine=None):
        if engine is not None:
            from app.core.worker_lock import WorkerLock
            self.worker_lock = WorkerLock(engine)
            await self.worker_lock.acquire()
        try:
            await self.recover()
            self.stopping = False
            self.task = asyncio.create_task(self.run(), name="trackhound-job-worker")
        except BaseException:
            if self.worker_lock:
                await self.worker_lock.release()
                self.worker_lock = None
            raise

    async def stop(self):
        self.stopping = True
        self.wake.set()
        # Do not abandon a native write in a thread. Its own execution deadline applies.
        if self.execution and self.execution.kind not in EDITS:
            self.execution.cancelled.set()
        interrupted = False
        try:
            if self.task:
                # A lifespan cancellation must not propagate into a worker
                # awaiting a native write in a thread or release its lifetime
                # lock while that write is still running. A hard process kill
                # is handled separately by persisted interrupted-job recovery.
                while not self.task.done():
                    try:
                        await asyncio.shield(self.task)
                    except asyncio.CancelledError:
                        if self.task.cancelled():
                            raise
                        interrupted = True
                await self.task
                self.task = None
        finally:
            if self.worker_lock:
                await self.worker_lock.release()
                self.worker_lock = None
        if interrupted:
            raise asyncio.CancelledError

    async def claim(self):
        async with self.coordination, async_session_maker() as db:
            next_id = select(Job.id).where(Job.status == "queued").order_by(Job.id).limit(1).scalar_subquery()
            job_id = await db.scalar(update(Job).where(Job.id == next_id, Job.status == "queued").values(
                status="running", started_at=utcnow()).returning(Job.id))
            if job_id:
                # A running reevaluation may have one coalesced successor for a
                # newer policy. Media/scan reservations stay held until finish.
                await db.execute(update(Job).where(Job.id == job_id, Job.kind == "reevaluate").values(active_key=None))
            await db.commit()
            return job_id

    async def run(self):
        while not self.stopping:
            self.wake.clear()
            try:
                job_id = await self.claim()
                if job_id:
                    await self.execute(job_id)
                    continue
            except Exception:
                logger.exception("Job worker iteration failed; retrying the queue shortly")
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=2)
            except TimeoutError:
                pass

    async def execute(self, job_id):
        async with async_session_maker() as db:
            job = await db.get(Job, job_id)
            if not job or job.status != "running":
                return
            execution = JobExecution(job.id, job.user_id, kind=job.kind)
            self.execution = execution
            if job.cancel_requested:
                execution.cancelled.set()
            kind, payload, user_id = job.kind, job.payload, job.user_id
        token = current_job.set(execution)
        result, outcome, error = {}, "completed", None
        try:
            if execution.cancelled.is_set():
                outcome = "cancelled"
            elif kind == "scan":
                result, outcome = await self.execute_scan(user_id, payload)
            elif kind == "reevaluate":
                from app.core.reevaluation import reevaluate_catalog
                result, outcome = await reevaluate_catalog(user_id, payload, self.save_progress)
            else:
                result, outcome = await self.execute_media(user_id, kind, payload)
        except Exception as exc:
            # HTTP errors contain reviewed, actionable safety messages; unexpected
            # exceptions are logged locally without persisting credentials/URLs.
            if isinstance(exc, HTTPException):
                error = str(exc.detail)
            else:
                logger.exception("Job %s failed", job_id)
                error = "Job failed unexpectedly. Check the application log and rescan before retrying a media edit."
            outcome = "cancelled" if execution.cancelled.is_set() and kind not in EDITS else "failed"
        finally:
            current_job.reset(token)
            self.execution = None
        # Retry only the outcome write, never the physical operation. Do not
        # claim more work while a temporarily unavailable DB cannot record it.
        while True:
            try:
                async with async_session_maker() as db:
                    await db.execute(update(Job).where(Job.id == job_id).values(
                        status=outcome, result=result, error=error, active_key=None, finished_at=utcnow()))
                    await self.prune_history(db, user_id)
                    await db.commit()
                break
            except OperationalError:
                logger.exception("Cannot persist job %s outcome; the operation will not be repeated", job_id)
                if self.stopping:
                    break  # Startup will report this still-running row as interrupted.
                await asyncio.sleep(2)

    async def prune_history(self, db, user_id):
        old = select(Job.id).where(Job.user_id == user_id, ~Job.status.in_(ACTIVE)).order_by(
            Job.finished_at.desc().nulls_last(), Job.id.desc()).offset(HISTORY_LIMIT)
        await db.execute(delete(Job).where(Job.id.in_(old)))

    async def execute_scan(self, user_id, payload):
        from app.core.encryption import decrypt_value
        from app.core.scanner import run_scan
        from app.core.scan_state import scan_state_manager

        async with async_session_maker() as db:
            locations = (await db.scalars(select(ScanLocation).where(
                ScanLocation.user_id == user_id, ScanLocation.id.in_(payload["location_ids"]), ScanLocation.enabled == True))).all()
            if len(locations) != len(payload["location_ids"]):
                raise HTTPException(409, "Scan locations changed. Review the locations and start a new scan.")
            paths = [loc.path for loc in locations]
            types = {loc.path: loc.media_type for loc in locations}
            user = await db.get(User, user_id)
            warning = None
            try:
                plex_token = decrypt_value(user.plex_token) if user.plex_token else None
            except ValueError:
                plex_token = None
                warning = "Stored Plex credentials are unavailable. Local scanning continues; sign in again to reconnect Plex."
        await run_scan(paths, types, user_id, incremental=payload["incremental"], user_plex_token=plex_token, plex_warning=warning)
        status = await scan_state_manager.get_status(user_id)
        return {"message": f"Scan {status.outcome}.", "files_scanned": status.files_scanned}, status.outcome

    async def execute_media(self, user_id, kind, payload):
        from app.api import media
        from app.models.schemas import AudioTrackRemovalRequest, UpdateDefaultAudioRequest

        if kind in ("rescan_file", "rescan_show"):
            async with async_session_maker() as db:
                if kind == "rescan_show" and not await db.scalar(select(Show.id).where(Show.user_id == user_id, Show.id == payload["show_id"])):
                    raise HTTPException(404, "The title is no longer in this catalog. Refresh the library.")
                ids = (await db.scalars(select(MediaFile.id).where(MediaFile.user_id == user_id,
                    MediaFile.show_id == payload["show_id"] if kind == "rescan_show" else MediaFile.id == payload["file_id"]).order_by(MediaFile.id))).all()
                if kind == "rescan_file" and not ids:
                    raise HTTPException(404, "The file is no longer in this catalog. Refresh the library.")
            succeeded, failed, errors = 0, 0, []
            for file_id in ids:
                if current_job.get().cancelled.is_set():
                    break
                async with async_session_maker() as db:
                    user = await db.get(User, user_id)
                    try:
                        await media.rescan_media_file(file_id, user, db)
                        await db.commit()
                        succeeded += 1
                    except HTTPException as exc:
                        await db.rollback()
                        if current_job.get().cancelled.is_set():
                            break
                        failed += 1
                        if len(errors) < 50:
                            errors.append(f"File #{file_id}: {exc.detail}")
                await self.save_progress({"files_total": len(ids), "files_scanned": succeeded + failed,
                    "succeeded": succeeded, "failed": failed, "errors": errors}, force=True)
            outcome = "cancelled" if current_job.get().cancelled.is_set() else "completed_with_errors" if failed else "completed"
            return {"message": f"Rescan {outcome}.", "succeeded": succeeded, "failed": failed}, outcome
        async with async_session_maker() as db:
            user = await db.get(User, user_id)
            if kind == "default_audio":
                response = await media.update_media_file_default_audio(payload["file_id"], UpdateDefaultAudioRequest(**payload["request"]), user, db)
            elif kind == "remove_audio":
                response = await media.remove_media_file_audio_tracks(payload["file_id"], AudioTrackRemovalRequest(**payload["request"]), user, db)
            else:
                raise ValueError("Unknown job kind")
            await db.commit()
            result = response.model_dump(mode="json", exclude={"media_file"})
            result["file_id"] = payload["file_id"]
            return result, "completed"

    async def save_progress(self, progress, *, force=False):
        execution = current_job.get()
        if not execution:
            return
        if not force and time.monotonic() - execution.last_progress_write < 1:
            return
        async with async_session_maker() as db:
            await db.execute(update(Job).where(Job.id == execution.job_id).values(progress=progress))
            await db.commit()
        execution.last_progress_write = time.monotonic()

    async def cancel(self, db, job):
        if job.status not in ACTIVE:
            raise HTTPException(409, "This job has already finished.")
        if job.status == "running" and job.kind in EDITS:
            raise HTTPException(409, "A media edit is already running. It must finish safely; it cannot be cancelled mid-write.")
        job.cancel_requested = True
        if job.status == "queued":
            job.status, job.active_key, job.finished_at = "cancelled", None, utcnow()
            await db.flush()
            await self.prune_history(db, job.user_id)
        await db.commit()
        if self.execution and self.execution.job_id == job.id:
            self.execution.cancelled.set()
        return job


job_manager = JobManager()


def scan_status(job):
    progress = dict(job.progress)
    progress.update(is_running=job.status in ACTIVE, job_id=job.id, job_status=job.status,
        cancel_requested=job.cancel_requested, started_at=job.started_at or job.created_at,
        finished_at=job.finished_at)
    if job.status in ACTIVE:
        progress["outcome"] = "running"
    if job.status in ("interrupted", "failed"):
        errors = progress.get("errors", [])
        extra = [job.error] if job.error else [] if errors else ["Job failed"]
        progress.update(outcome="failed", errors=[*errors, *extra][:50],
                        error_count=progress.get("error_count", 0) + len(extra))
    elif job.status == "queued":
        progress.update(outcome="running", current_file="Queued…")
    elif job.status == "cancelled":
        progress["outcome"] = "cancelled"
    return ScanStatus(**progress)
