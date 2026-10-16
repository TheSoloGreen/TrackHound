"""Owned job progress, retained outcomes and cancellation."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.jobs import ACTIVE, job_manager
from app.models.database import get_db
from app.models.entities import Job, User
from app.models.schemas import JobListResponse, JobResponse

router = APIRouter()


async def catalog_idle(current_user: Annotated[User, Depends(get_current_user)],
                       db: Annotated[AsyncSession, Depends(get_db)]):
    async with job_manager.catalog_mutation(db, current_user.id):
        yield


@router.get("", response_model=JobListResponse)
async def list_jobs(current_user: Annotated[User, Depends(get_current_user)],
                    db: Annotated[AsyncSession, Depends(get_db)],
                    offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    scope = Job.user_id == current_user.id
    total = await db.scalar(select(func.count(Job.id)).where(scope))
    jobs = (await db.scalars(select(Job).where(scope).order_by(Job.status.in_(ACTIVE).desc(), Job.id.desc()).offset(offset).limit(limit))).all()
    return JobListResponse(items=jobs, total=total)


async def owned_job(db, user_id, job_id):
    job = await db.scalar(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: int, current_user: Annotated[User, Depends(get_current_user)],
                  db: Annotated[AsyncSession, Depends(get_db)]):
    return await owned_job(db, current_user.id, job_id)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: int, current_user: Annotated[User, Depends(get_current_user)],
                     db: Annotated[AsyncSession, Depends(get_db)]):
    async with job_manager.coordination:
        job = await owned_job(db, current_user.id, job_id)
        await db.refresh(job)
        return await job_manager.cancel(db, job)
