"""Media API endpoints for querying shows, seasons, and files."""

from math import ceil
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import get_current_user
from app.models.database import get_db
from app.models.entities import User, Show, Season, MediaFile, AudioTrack, ScanLocation
from app.models.schemas import (
    AudioTrackResponse,
    ShowResponse,
    ShowDetailResponse,
    ShowUpdate,
    ShowListResponse,
    SeasonResponse,
    SeasonDetailResponse,
    MediaFileResponse,
    MediaFileListResponse,
    DashboardStats,
)

router = APIRouter()


def _build_issue_predicate(*patterns: str):
    """Build a SQL predicate that matches any known issue representation."""
    return or_(*[MediaFile.issue_details.ilike(pattern) for pattern in patterns])


def _media_user_scope_filters(current_user: User) -> list:
    """Return media filters scoped to the current user when ownership fields exist."""
    filters = []
    if hasattr(MediaFile, "user_id"):
        filters.append(MediaFile.user_id == current_user.id)
    return filters


def _show_user_scope_filters(current_user: User) -> list:
    """Return show filters scoped to the current user when ownership fields exist."""
    filters = []
    if hasattr(Show, "user_id"):
        filters.append(Show.user_id == current_user.id)
    return filters


def _scan_location_user_scope_filters(current_user: User) -> list:
    """Return scan-location filters scoped to the current user when ownership fields exist."""
    filters = []
    if hasattr(ScanLocation, "user_id"):
        filters.append(ScanLocation.user_id == current_user.id)
    return filters


def _build_audio_track_responses(audio_tracks: list) -> list[AudioTrackResponse]:
    """Build AudioTrackResponse list from ORM objects."""
    return [
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
        for at in sorted(audio_tracks, key=lambda a: a.track_index)
    ]


def _build_media_file_response(mf: MediaFile) -> MediaFileResponse:
    """Build MediaFileResponse from ORM object."""
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
        audio_tracks=_build_audio_track_responses(mf.audio_tracks),
    )


# ============== Dashboard Stats ==============


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get dashboard statistics."""
    show_scope_filters = _show_user_scope_filters(current_user)
    media_scope_filters = _media_user_scope_filters(current_user)
    scan_scope_filters = _scan_location_user_scope_filters(current_user)

    total_titles = await db.scalar(select(func.count(Show.id)).where(*show_scope_filters)) or 0

    movie_count = await db.scalar(
        select(func.count(Show.id)).where(*show_scope_filters, Show.media_type == "movie")
    ) or 0
    tv_count = await db.scalar(
        select(func.count(Show.id)).where(*show_scope_filters, Show.media_type == "tv")
    ) or 0
    anime_count = await db.scalar(
        select(func.count(Show.id)).where(*show_scope_filters, Show.media_type == "anime")
    ) or 0

    total_files = await db.scalar(select(func.count(MediaFile.id)).where(*media_scope_filters)) or 0

    files_with_issues = await db.scalar(
        select(func.count(MediaFile.id)).where(*media_scope_filters, MediaFile.has_issues == True)
    ) or 0

    missing_english_predicate = _build_issue_predicate(
        "%Missing English audio track%",
        "%Missing English audio for dual audio (anime)%",
        "%missing_english%",
    )
    missing_japanese_predicate = _build_issue_predicate(
        "%Missing Japanese audio track (anime)%",
        "%Missing Japanese audio for dual audio (anime)%",
        "%missing_japanese%",
    )
    missing_dual_audio_predicate = _build_issue_predicate(
        "%Missing dual audio (English + Japanese) for anime%",
        "%Missing English audio for dual audio (anime)%",
        "%Missing Japanese audio for dual audio (anime)%",
        "%missing_dual_audio%",
    )

    missing_english_count = await db.scalar(
        select(func.count(MediaFile.id)).where(*media_scope_filters, missing_english_predicate)
    ) or 0
    missing_japanese_count = await db.scalar(
        select(func.count(MediaFile.id)).where(*media_scope_filters, missing_japanese_predicate)
    ) or 0
    missing_dual_audio_count = await db.scalar(
        select(func.count(MediaFile.id)).where(*media_scope_filters, missing_dual_audio_predicate)
    ) or 0

    last_scan = await db.scalar(
        select(func.max(ScanLocation.last_scanned)).where(*scan_scope_filters)
    )
    if last_scan is None:
        last_scan = await db.scalar(
            select(func.max(MediaFile.last_scanned)).where(*media_scope_filters)
        )

    return DashboardStats(
        total_titles=total_titles,
        total_files=total_files,
        total_files_with_issues=files_with_issues,
        movie_count=movie_count,
        tv_count=tv_count,
        anime_count=anime_count,
        missing_english_count=missing_english_count,
        missing_japanese_count=missing_japanese_count,
        missing_dual_audio_count=missing_dual_audio_count,
        last_scan=last_scan,
    )


# ============== Shows / Library ==============


@router.get("/shows", response_model=ShowListResponse)
async def list_shows(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    media_type: Optional[str] = None,
    is_anime: Optional[bool] = None,
    has_issues: Optional[bool] = None,
    search: Optional[str] = None,
):
    """List all titles with pagination and filters."""
    # Subqueries for season-based counts (TV/anime)
    season_count_sq = (
        select(Season.show_id, func.count(Season.id).label("season_count"))
        .join(Show, Show.id == Season.show_id)
        .where(Show.user_id == current_user.id)
        .group_by(Season.show_id)
        .subquery()
    )
    episode_count_sq = (
        select(Season.show_id, func.count(MediaFile.id).label("episode_count"))
        .join(MediaFile, MediaFile.season_id == Season.id)
        .join(Show, Show.id == Season.show_id)
        .where(Show.user_id == current_user.id, MediaFile.user_id == current_user.id)
        .group_by(Season.show_id)
        .subquery()
    )
    season_issues_sq = (
        select(Season.show_id, func.count(MediaFile.id).label("season_issues"))
        .join(MediaFile, MediaFile.season_id == Season.id)
        .join(Show, Show.id == Season.show_id)
        .where(MediaFile.has_issues == True, Show.user_id == current_user.id, MediaFile.user_id == current_user.id)
        .group_by(Season.show_id)
        .subquery()
    )

    # Subqueries for direct file counts (movies)
    direct_file_count_sq = (
        select(
            MediaFile.show_id,
            func.count(MediaFile.id).label("direct_file_count"),
        )
        .where(
            MediaFile.show_id.isnot(None),
            MediaFile.season_id.is_(None),
            MediaFile.user_id == current_user.id,
        )
        .group_by(MediaFile.show_id)
        .subquery()
    )
    direct_issues_sq = (
        select(
            MediaFile.show_id,
            func.count(MediaFile.id).label("direct_issues"),
        )
        .where(
            MediaFile.show_id.isnot(None),
            MediaFile.season_id.is_(None),
            MediaFile.has_issues == True,
            MediaFile.user_id == current_user.id,
        )
        .group_by(MediaFile.show_id)
        .subquery()
    )

    # Base query
    query = (
        select(
            Show,
            func.coalesce(season_count_sq.c.season_count, 0).label("season_count"),
            func.coalesce(episode_count_sq.c.episode_count, 0).label("episode_count"),
            func.coalesce(season_issues_sq.c.season_issues, 0).label("season_issues"),
            func.coalesce(direct_file_count_sq.c.direct_file_count, 0).label("direct_file_count"),
            func.coalesce(direct_issues_sq.c.direct_issues, 0).label("direct_issues"),
        )
        .outerjoin(season_count_sq, season_count_sq.c.show_id == Show.id)
        .outerjoin(episode_count_sq, episode_count_sq.c.show_id == Show.id)
        .outerjoin(season_issues_sq, season_issues_sq.c.show_id == Show.id)
        .outerjoin(direct_file_count_sq, direct_file_count_sq.c.show_id == Show.id)
        .outerjoin(direct_issues_sq, direct_issues_sq.c.show_id == Show.id)
    ).where(Show.user_id == current_user.id)

    # Apply filters
    filters = []
    if media_type is not None:
        filters.append(Show.media_type == media_type)
    if is_anime is not None:
        filters.append(Show.is_anime == is_anime)
    if search:
        filters.append(Show.title.ilike(f"%{search}%"))
    if has_issues is not None:
        total_issues = (
            func.coalesce(season_issues_sq.c.season_issues, 0)
            + func.coalesce(direct_issues_sq.c.direct_issues, 0)
        )
        if has_issues:
            filters.append(total_issues > 0)
        else:
            filters.append(total_issues == 0)

    if filters:
        query = query.where(and_(*filters))

    # Total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Pagination
    query = query.order_by(Show.title).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    rows = result.all()

    show_responses = []
    for row in rows:
        show = row[0]
        season_count = row[1]
        episode_count = row[2]
        s_issues = row[3]
        direct_files = row[4]
        d_issues = row[5]

        show_responses.append(
            ShowResponse(
                id=show.id,
                title=show.title,
                media_type=show.media_type,
                is_anime=show.is_anime,
                anime_source=show.anime_source,
                thumb_url=show.thumb_url,
                season_count=season_count,
                episode_count=episode_count,
                file_count=direct_files,
                issues_count=s_issues + d_issues,
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
    """Get title details with seasons (TV/anime) or files (movies)."""
    result = await db.execute(
        select(Show)
        .options(
            selectinload(Show.seasons),
            selectinload(Show.media_files).selectinload(MediaFile.audio_tracks),
        )
        .where(Show.id == show_id, Show.user_id == current_user.id)
    )
    show = result.scalar_one_or_none()

    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Title not found",
        )

    # Build season responses (TV/anime)
    season_responses = []
    total_episode_count = 0
    total_season_issues = 0

    season_ids = [s.id for s in show.seasons]
    season_counts = {}
    if season_ids:
        count_result = await db.execute(
            select(
                MediaFile.season_id,
                func.count(MediaFile.id).label("episode_count"),
                func.count(MediaFile.id).filter(MediaFile.has_issues == True).label("issues_count"),
            )
            .where(
                MediaFile.season_id.in_(season_ids),
                MediaFile.user_id == current_user.id,
            )
            .group_by(MediaFile.season_id)
        )
        for row in count_result.all():
            season_counts[row[0]] = {"episodes": row[1], "issues": row[2]}

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
        total_episode_count += counts["episodes"]
        total_season_issues += counts["issues"]

    # Build direct file responses (movies — files linked via show_id, no season)
    direct_files = [mf for mf in show.media_files if mf.season_id is None]
    media_file_responses = [_build_media_file_response(mf) for mf in direct_files]
    direct_issues = sum(1 for mf in direct_files if mf.has_issues)

    return ShowDetailResponse(
        id=show.id,
        title=show.title,
        media_type=show.media_type,
        is_anime=show.is_anime,
        anime_source=show.anime_source,
        thumb_url=show.thumb_url,
        season_count=len(season_responses),
        episode_count=total_episode_count,
        file_count=len(media_file_responses),
        issues_count=total_season_issues + direct_issues,
        created_at=show.created_at,
        updated_at=show.updated_at,
        seasons=season_responses,
        media_files=media_file_responses,
    )


@router.patch("/shows/{show_id}", response_model=ShowResponse)
async def update_show(
    show_id: int,
    updates: ShowUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update title properties."""
    result = await db.execute(select(Show).where(Show.id == show_id, Show.user_id == current_user.id))
    show = result.scalar_one_or_none()

    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Title not found",
        )

    if updates.media_type is not None:
        show.media_type = updates.media_type
        if updates.media_type == "anime":
            show.is_anime = True
        elif updates.media_type in ("tv", "movie"):
            show.is_anime = False
    if updates.is_anime is not None:
        show.is_anime = updates.is_anime
        if updates.is_anime and not show.anime_source:
            show.anime_source = "manual"
    if updates.anime_source is not None:
        show.anime_source = updates.anime_source

    await db.flush()

    # Counts
    season_count = await db.scalar(
        select(func.count(Season.id)).where(Season.show_id == show.id)
    ) or 0
    episode_count = await db.scalar(
        select(func.count(MediaFile.id)).join(Season).where(
            Season.show_id == show.id,
            MediaFile.user_id == current_user.id,
        )
    ) or 0
    file_count = await db.scalar(
        select(func.count(MediaFile.id)).where(
            MediaFile.show_id == show.id,
            MediaFile.season_id.is_(None),
            MediaFile.user_id == current_user.id,
        )
    ) or 0
    issues_count = await db.scalar(
        select(func.count(MediaFile.id)).where(
            or_(
                MediaFile.season_id.in_(select(Season.id).where(Season.show_id == show.id)),
                and_(MediaFile.show_id == show.id, MediaFile.season_id.is_(None)),
            ),
            MediaFile.has_issues == True,
            MediaFile.user_id == current_user.id,
        )
    ) or 0

    return ShowResponse(
        id=show.id,
        title=show.title,
        media_type=show.media_type,
        is_anime=show.is_anime,
        anime_source=show.anime_source,
        thumb_url=show.thumb_url,
        season_count=season_count,
        episode_count=episode_count,
        file_count=file_count,
        issues_count=issues_count,
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
        .where(
            Season.show_id == show_id,
            Season.season_number == season_number,
            Season.show.has(Show.user_id == current_user.id),
        )
    )
    season = result.scalar_one_or_none()

    if not season:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Season not found",
        )

    media_files = [
        _build_media_file_response(mf)
        for mf in sorted(season.media_files, key=lambda m: m.episode_number or 0)
    ]

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
    query = select(MediaFile).options(selectinload(MediaFile.audio_tracks)).where(
        MediaFile.user_id == current_user.id
    )

    filters = []
    if has_issues is not None:
        filters.append(MediaFile.has_issues == has_issues)
    if show_id is not None:
        # Match files linked via season OR directly via show_id
        filters.append(
            or_(
                MediaFile.season_id.in_(
                    select(Season.id).where(
                        Season.show_id == show_id,
                        Season.show.has(Show.user_id == current_user.id),
                    )
                ),
                MediaFile.show_id == show_id,
            )
        )
    if search:
        filters.append(MediaFile.filename.ilike(f"%{search}%"))

    if filters:
        query = query.where(and_(*filters))

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    query = query.order_by(MediaFile.file_path).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    files = result.scalars().all()

    file_responses = [_build_media_file_response(mf) for mf in files]

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
        .where(MediaFile.id == file_id, MediaFile.user_id == current_user.id)
    )
    mf = result.scalar_one_or_none()

    if not mf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file not found",
        )

    return _build_media_file_response(mf)
