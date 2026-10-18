"""Evaluate saved audio evidence only. Never inspect, probe, or edit media."""

import asyncio
import sqlite3

from sqlalchemy import and_, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload

from app.core.analyzer import ANALYSIS_VERSION
from app.core.issue_catalog import apply_evaluation
from app.core.job_context import current_job
from app.core.policy_revision import evaluation_policy, evaluation_revision
from app.core.preference_engine import AudioPreferences, EVALUATION_VERSION, PreferenceEngine
from app.core.user_settings import load_user_settings
from app.models.database import async_session_maker
from app.models.entities import Job, MediaFile
from app.models.schemas import EvaluationStatus

BATCH_SIZE = 200


def reevaluation_payload(settings):
    return {"policy": evaluation_policy(settings.audio_preferences),
            "policy_revision": evaluation_revision(settings.audio_preferences)}


async def evaluation_status(db, user_id, settings=None):
    settings = settings or await load_user_settings(db, user_id)
    revision = evaluation_revision(settings.audio_preferences)
    eligible = MediaFile.analysis_version == ANALYSIS_VERSION
    current = and_(eligible, MediaFile.issue_policy_revision == revision,
                   MediaFile.issue_evaluation_version == EVALUATION_VERSION)
    total, available, fresh = (await db.execute(select(
        func.count(MediaFile.id), func.count(MediaFile.id).filter(eligible),
        func.count(MediaFile.id).filter(current)).where(MediaFile.user_id == user_id))).one()
    latest = await db.scalar(select(Job).where(Job.user_id == user_id, Job.kind == "reevaluate").order_by(
        Job.status.in_(("queued", "running")).desc(), Job.id.desc()).limit(1))
    return EvaluationStatus(policy_revision=revision, files_total=total, files_current=fresh,
                            files_pending=available - fresh, files_needing_scan=total - available, latest_job=latest)


def track_evidence(track):
    return {"index": track.track_index, **{key: getattr(track, key) for key in (
        "language", "language_raw", "codec", "channels", "channel_layout", "bitrate", "is_default", "is_forced", "title")}}


async def reevaluate_catalog(user_id, payload, save_progress):
    preferences = AudioPreferences(**payload["policy"])
    revision = evaluation_revision(preferences)
    if revision != payload["policy_revision"]:
        raise ValueError("Invalid policy revision in reevaluation job")
    engine = PreferenceEngine(preferences)
    async with async_session_maker() as db:
        maximum, total = (await db.execute(select(func.max(MediaFile.id), func.count(MediaFile.id)).where(
            MediaFile.user_id == user_id))).one()
    counts = {"files_total": total, "files_scanned": 0, "reevaluated": 0, "unchanged": 0, "needs_scan": 0,
              "policy_revision": revision}
    await save_progress(counts, force=True)
    cursor = 0
    outcome = "completed"
    while cursor < (maximum or 0):
        if current_job.get().cancelled.is_set():
            outcome = "cancelled"
            break
        for attempt in range(4):
            try:
                async with async_session_maker() as db:
                    settings = await load_user_settings(db, user_id)
                    if evaluation_revision(settings.audio_preferences) != revision:
                        outcome = "superseded"
                        break
                    files = (await db.scalars(select(MediaFile).where(MediaFile.user_id == user_id,
                        MediaFile.id > cursor, MediaFile.id <= maximum).order_by(MediaFile.id).limit(BATCH_SIZE).options(
                            selectinload(MediaFile.audio_tracks), selectinload(MediaFile.show)))).all()
                    if not files:
                        cursor = maximum
                        break
                    batch = {"reevaluated": 0, "unchanged": 0, "needs_scan": 0}
                    for media_file in files:
                        if media_file.analysis_version != ANALYSIS_VERSION:
                            # Preserve old findings when the cache is absent/untrusted.
                            batch["needs_scan"] += 1
                        elif media_file.issue_policy_revision == revision and media_file.issue_evaluation_version == EVALUATION_VERSION:
                            batch["unchanged"] += 1
                        else:
                            apply_evaluation(media_file, engine, [track_evidence(t) for t in media_file.audio_tracks],
                                             bool(media_file.show and media_file.show.is_anime))
                            batch["reevaluated"] += 1
                    if current_job.get().cancelled.is_set():
                        outcome = "cancelled"
                        break  # The context rolls back this batch; prior commits remain.
                    await db.commit()
                    cursor = files[-1].id
                    counts = {**counts, "files_scanned": counts["files_scanned"] + len(files),
                              **{key: counts[key] + value for key, value in batch.items()}}
                await save_progress(counts, force=True)
                break
            except OperationalError as exc:
                code = getattr(getattr(exc, "orig", None), "sqlite_errorcode", 0) or 0
                if code & 0xff not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or attempt == 3:
                    raise
                await asyncio.sleep(0.1 * 2 ** attempt)
        if outcome != "completed":
            break
    message = ("Audio rules changed again; this job was superseded by the newer policy." if outcome == "superseded"
               else f"Cached audio reevaluation {outcome}. No media files were read or edited.")
    if counts["needs_scan"]:
        message += f" {counts['needs_scan']} files need a physical scan because cached analysis is unavailable."
    return {**counts, "message": message}, outcome
