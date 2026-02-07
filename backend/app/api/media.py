"""Media API endpoints for querying shows, seasons, and files."""

from math import ceil
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import get_current_user
from app.models.database import get_db
from app.models.entities import User, Show, Season, MediaFile, AudioTrack
from app.models.schemas import (
    ShowResponse,
    ShowDetailResponse,
    ShowUpdate,
    ShowListResponse,
    SeasonDetailResponse,
    MediaFileResponse,
    MediaFileListResponse,
    DashboardStats,
)

router = APIRouter()


# ============== Dashboard Stats ==============


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get dashboard statistics."""
    # Total shows
    total_shows = await db.scalar(select(func.count(Show.id)))

    # Anime vs non-anime
    anime_count = await db.scalar(
        select(func.count(Show.id)).where(Show.is_anime == True)
    )
    non_anime_count = total_shows - anime_count

    # Total episodes (media files with season association)
    total_episodes = await db.scalar(
        select(func.count(MediaFile.id)).where(MediaFile.season_id.isnot(None))
    )

    # Files with issues
    files_with_issues = await db.scalar(
        select(func.count(MediaFile.id)).where(MediaFile.has_issues == True)
    )

    # TODO: Implement detailed issue counts once preference engine is complete
    # For now, return placeholder values
    return DashboardStats(
        total_shows=total_shows or 0,
        total_episodes=total_episodes or 0,
        total_files_with_issues=files_with_issues or 0,
        anime_count=anime_count or 0,
        non_anime_count=non_anime_count or 0,
        missing_english_count=0,
        missing_japanese_count=0,
        missing_dual_audio_count=0,
        last_scan=None,
    )


# ============== Shows ==============


@router.get("/shows", response_model=ShowListResponse)
async def list_shows(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    is_anime: Optional[bool] = None,
    has_issues: Optional[bool] = None,
    search: Optional[str] = None,
):
    """List all shows with pagination and filters."""
    # Build subqueries for counts (avoids N+1 queries)
    season_count_sq = (
        select(Season.show_id, func.count(Season.id).label("season_count"))
        .group_by(Season.show_id)
        .subquery()
    )
    episode_count_sq = (
        select(Season.show_id, func.count(MediaFile.id).label("episode_count"))
        .join(MediaFile, MediaFile.season_id == Season.id)
        .group_by(Season.show_id)
        .subquery()
    )
    issues_count_sq = (
        select(Season.show_id, func.count(MediaFile.id).label("issues_count"))
        .join(MediaFile, MediaFile.season_id == Season.id)
        .where(MediaFile.has_issues == True)
        .group_by(Season.show_id)
        .subquery()
    )

    # Base query with counts joined
    query = (
        select(
            Show,
            func.coalesce(season_count_sq.c.season_count, 0).label("season_count"),
            func.coalesce(episode_count_sq.c.episode_count, 0).label("episode_count"),
            func.coalesce(issues_count_sq.c.issues_count, 0).label("issues_count"),
        )
        .outerjoin(season_count_sq, season_count_sq.c.show_id == Show.id)
        .outerjoin(episode_count_sq, episode_count_sq.c.show_id == Show.id)
        .outerjoin(issues_count_sq, issues_count_sq.c.show_id == Show.id)
    )

    # Apply filters
    filters = []
    if is_anime is not None:
        filters.append(Show.is_anime == is_anime)
    if search:
        filters.append(Show.title.ilike(f"%{search}%"))
    if has_issues is not None:
        issues_col = func.coalesce(issues_count_sq.c.issues_count, 0)
        if has_issues:
            filters.append(issues_col > 0)
        else:
            filters.append(issues_col == 0)

    if filters:
        query = query.where(and_(*filters))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination
    query = query.order_by(Show.title).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    rows = result.all()

    # Build responses from joined data
    show_responses = []
    for row in rows:
        show = row[0]
        show_responses.append(
            ShowResponse(
                id=show.id,
                title=show.title,
                is_anime=show.is_anime,
                anime_source=show.anime_source,
                thumb_url=show.thumb_url,
                season_count=row[1],
                episode_count=row[2],
                issues_count=row[3],
                created_at=show.created_at,
                updated_at=show.updated_at,
            )
        )

    return ShowListResponse(
        items=show_responses,
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total > 0 else 1,
    )


@router.get("/shows/{show_id}", response_model=ShowDetailResponse)
async def get_show(
    show_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get show details with seasons."""
    result = await db.execute(
        select(Show)
        .options(selectinload(Show.seasons))
        .where(Show.id == show_id)
    )
    show = result.scalar_one_or_none()

    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Show not found",
        )

    # Build season responses with counts (batch query to avoid N+1)
    from app.models.schemas import SeasonResponse

    season_ids = [s.id for s in show.seasons]
    season_counts = {}
    if season_ids:
        count_result = await db.execute(
            select(
                MediaFile.season_id,
                func.count(MediaFile.id).label("episode_count"),
                func.count(MediaFile.id).filter(MediaFile.has_issues == True).label("issues_count"),
            )
            .where(MediaFile.season_id.in_(season_ids))
            .group_by(MediaFile.season_id)
        )
        for row in count_result.all():
            season_counts[row[0]] = {"episodes": row[1], "issues": row[2]}

    season_responses = []
    for season in sorted(show.seasons, key=lambda s: s.season_number):
        counts = season_counts.get(season.id, {"episodes": 0, "issues": 0})
        season_responses.append(
            SeasonResponse(
                id=season.id,
                season_number=season.season_number,
                episode_count=counts["episodes"],
                issues_count=counts["issues"],
            )
        )

    return ShowDetailResponse(
        id=show.id,
        title=show.title,
        is_anime=show.is_anime,
        anime_source=show.anime_source,
        thumb_url=show.thumb_url,
        season_count=len(season_responses),
        episode_count=sum(s.episode_count for s in season_responses),
        issues_count=sum(s.issues_count for s in season_responses),
        created_at=show.created_at,
        updated_at=show.updated_at,
        seasons=season_responses,
    )


@router.patch("/shows/{show_id}", response_model=ShowResponse)
async def update_show(
    show_id: int,
    updates: ShowUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update show properties (e.g., mark as anime)."""
    result = await db.execute(select(Show).where(Show.id == show_id))
    show = result.scalar_one_or_none()

    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Show not found",
        )

    if updates.is_anime is not None:
        show.is_anime = updates.is_anime
        if updates.is_anime and not show.anime_source:
            show.anime_source = "manual"
    if updates.anime_source is not None:
        show.anime_source = updates.anime_source

    await db.flush()

    # Get counts
    season_count = await db.scalar(
        select(func.count(Season.id)).where(Season.show_id == show.id)
    )
    episode_count = await db.scalar(
        select(func.count(MediaFile.id)).join(Season).where(Season.show_id == show.id)
    )
    issues_count = await db.scalar(
        select(func.count(MediaFile.id))
        .join(Season)
        .where(Season.show_id == show.id, MediaFile.has_issues == True)
    )

    return ShowResponse(
        id=show.id,
        title=show.title,
        is_anime=show.is_anime,
        anime_source=show.anime_source,
        thumb_url=show.thumb_url,
        season_count=season_count or 0,
        episode_count=episode_count or 0,
        issues_count=issues_count or 0,
        created_at=show.created_at,
        updated_at=show.updated_at,
    )


# ============== Seasons ==============


@router.get("/shows/{show_id}/seasons/{season_number}", response_model=SeasonDetailResponse)
async def get_season(
    show_id: int,
    season_number: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get season details with episodes."""
    result = await db.execute(
        select(Season)
        .options(selectinload(Season.media_files).selectinload(MediaFile.audio_tracks))
        .where(Season.show_id == show_id, Season.season_number == season_number)
    )
    season = result.scalar_one_or_none()

    if not season:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Season not found",
        )

    # Build media file responses
    from app.models.schemas import AudioTrackResponse

    media_files = []
    for mf in sorted(season.media_files, key=lambda m: m.episode_number or 0):
        audio_tracks = [
            AudioTrackResponse(
                id=at.id,
                track_index=at.track_index,
                language=at.language,
                language_raw=at.language_raw,
                codec=at.codec,
                channels=at.channels,
                channel_layout=at.channel_layout,
                bitrate=at.bitrate,
                is_default=at.is_default,
                is_forced=at.is_forced,
                title=at.title,
            )
            for at in sorted(mf.audio_tracks, key=lambda a: a.track_index)
        ]
        media_files.append(
            MediaFileResponse(
                id=mf.id,
                file_path=mf.file_path,
                filename=mf.filename,
                episode_number=mf.episode_number,
                episode_title=mf.episode_title,
                file_size=mf.file_size,
                container_format=mf.container_format,
                duration_ms=mf.duration_ms,
                last_scanned=mf.last_scanned,
                has_issues=mf.has_issues,
                issue_details=mf.issue_details,
                audio_tracks=audio_tracks,
            )
        )

    return SeasonDetailResponse(
        id=season.id,
        season_number=season.season_number,
        episode_count=len(media_files),
        issues_count=sum(1 for mf in media_files if mf.has_issues),
        media_files=media_files,
    )


# ============== Media Files ==============


@router.get("/files", response_model=MediaFileListResponse)
async def list_media_files(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    has_issues: Optional[bool] = None,
    show_id: Optional[int] = None,
    search: Optional[str] = None,
):
    """List media files with pagination and filters."""
    # Base query
    query = select(MediaFile).options(selectinload(MediaFile.audio_tracks))

    # Apply filters
    filters = []
    if has_issues is not None:
        filters.append(MediaFile.has_issues == has_issues)
    if show_id is not None:
        filters.append(
            MediaFile.season_id.in_(
                select(Season.id).where(Season.show_id == show_id)
            )
        )
    if search:
        filters.append(MediaFile.filename.ilike(f"%{search}%"))

    if filters:
        query = query.where(and_(*filters))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination
    query = query.order_by(MediaFile.file_path).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    files = result.scalars().all()

    # Build responses
    from app.models.schemas import AudioTrackResponse

    file_responses = []
    for mf in files:
        audio_tracks = [
            AudioTrackResponse(
                id=at.id,
                track_index=at.track_index,
                language=at.language,
                language_raw=at.language_raw,
                codec=at.codec,
                channels=at.channels,
                channel_layout=at.channel_layout,
                bitrate=at.bitrate,
                is_default=at.is_default,
                is_forced=at.is_forced,
                title=at.title,
            )
            for at in sorted(mf.audio_tracks, key=lambda a: a.track_index)
        ]
        file_responses.append(
            MediaFileResponse(
                id=mf.id,
                file_path=mf.file_path,
                filename=mf.filename,
                episode_number=mf.episode_number,
                episode_title=mf.episode_title,
                file_size=mf.file_size,
                container_format=mf.container_format,
                duration_ms=mf.duration_ms,
                last_scanned=mf.last_scanned,
                has_issues=mf.has_issues,
                issue_details=mf.issue_details,
                audio_tracks=audio_tracks,
            )
        )

    return MediaFileListResponse(
        items=file_responses,
        total=total,
        page=page,
        page_size=page_size,
        pages=ceil(total / page_size) if total > 0 else 1,
    )


@router.get("/files/{file_id}", response_model=MediaFileResponse)
async def get_media_file(
    file_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get media file details with audio tracks."""
    result = await db.execute(
        select(MediaFile)
        .options(selectinload(MediaFile.audio_tracks))
        .where(MediaFile.id == file_id)
    )
    mf = result.scalar_one_or_none()

    if not mf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file not found",
        )

    from app.models.schemas import AudioTrackResponse

    audio_tracks = [
        AudioTrackResponse(
            id=at.id,
            track_index=at.track_index,
            language=at.language,
            language_raw=at.language_raw,
            codec=at.codec,
            channels=at.channels,
            channel_layout=at.channel_layout,
            bitrate=at.bitrate,
            is_default=at.is_default,
            is_forced=at.is_forced,
            title=at.title,
        )
        for at in sorted(mf.audio_tracks, key=lambda a: a.track_index)
    ]

    return MediaFileResponse(
        id=mf.id,
        file_path=mf.file_path,
        filename=mf.filename,
        episode_number=mf.episode_number,
        episode_title=mf.episode_title,
        file_size=mf.file_size,
        container_format=mf.container_format,
        duration_ms=mf.duration_ms,
        last_scanned=mf.last_scanned,
        has_issues=mf.has_issues,
        issue_details=mf.issue_details,
        audio_tracks=audio_tracks,
    )
