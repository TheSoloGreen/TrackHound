"""Scan API endpoints for managing scan locations and running scans."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.models.database import get_db
from app.models.entities import ScanLocation, User
from app.models.schemas import (
    DirectoryBrowseResponse,
    DirectoryEntry,
    ScanLocationCreate,
    ScanLocationResponse,
    ScanLocationUpdate,
    ScanMediaType,
    ScanStartRequest,
    ScanStatus,
    validate_media_root_path,
)

from app.core.scan_state import scan_state_manager

router = APIRouter()

# Root path for directory browsing (security boundary)
MEDIA_ROOT = "/media"


def _invalid_scan_input(message: str) -> HTTPException:
    """Build a consistent 400 validation response for scan endpoints."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "detail": "Invalid request input.",
            "errors": [message],
        },
    )


def _validate_scan_media_type(value: ScanMediaType | str) -> str:
    """Normalize media_type values to tv/movie/anime."""
    if isinstance(value, ScanMediaType):
        return value.value

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {item.value for item in ScanMediaType}:
            return normalized

    raise _invalid_scan_input("media_type must be one of: tv, movie, anime.")


# ============== Directory Browsing ==============


@router.get("/browse", response_model=DirectoryBrowseResponse)
async def browse_directories(
    current_user: Annotated[User, Depends(get_current_user)],
    path: str = Query(MEDIA_ROOT, description="Directory path to browse"),
):
    """List subdirectories at the given path for scan location selection."""
    try:
        resolved_path = validate_media_root_path(path)
    except ValueError as exc:
        raise _invalid_scan_input(str(exc)) from exc

    resolved = Path(resolved_path)
    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Directory not found",
        )

    directories = []
    try:
        for entry in sorted(resolved.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                directories.append(
                    DirectoryEntry(name=entry.name, path=str(entry))
                )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    return DirectoryBrowseResponse(
        current_path=str(resolved),
        directories=directories,
    )


# ============== Scan Locations ==============


@router.get("/locations", response_model=list[ScanLocationResponse])
async def list_scan_locations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List all configured scan locations."""
    result = await db.execute(
        select(ScanLocation)
        .where(ScanLocation.user_id == current_user.id)
        .order_by(ScanLocation.label)
    )
    locations = result.scalars().all()
    return locations


@router.post("/locations", response_model=ScanLocationResponse, status_code=status.HTTP_201_CREATED)
async def create_scan_location(
    location: ScanLocationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add a new scan location."""
    # Defensive validation before persistence
    try:
        normalized_path = validate_media_root_path(location.path)
    except ValueError as exc:
        raise _invalid_scan_input(str(exc)) from exc
    media_type = _validate_scan_media_type(location.media_type)

    # Check if path already exists for the current user
    result = await db.execute(
        select(ScanLocation).where(
            ScanLocation.user_id == current_user.id,
            ScanLocation.path == normalized_path,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Scan location with this path already exists",
        )

    new_location = ScanLocation(
        user_id=current_user.id,
        path=normalized_path,
        label=location.label,
        media_type=media_type,
        enabled=location.enabled,
    )
    db.add(new_location)
    await db.flush()
    await db.refresh(new_location)

    return new_location


@router.get("/locations/{location_id}", response_model=ScanLocationResponse)
async def get_scan_location(
    location_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get a specific scan location."""
    result = await db.execute(
        select(ScanLocation).where(
            ScanLocation.id == location_id,
            ScanLocation.user_id == current_user.id,
        )
    )
    location = result.scalar_one_or_none()

    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scan location not found",
        )

    return location


@router.patch("/locations/{location_id}", response_model=ScanLocationResponse)
async def update_scan_location(
    location_id: int,
    updates: ScanLocationUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update a scan location."""
    result = await db.execute(
        select(ScanLocation).where(
            ScanLocation.id == location_id,
            ScanLocation.user_id == current_user.id,
        )
    )
    location = result.scalar_one_or_none()

    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scan location not found",
        )

    if updates.label is not None:
        location.label = updates.label
    if updates.media_type is not None:
        location.media_type = _validate_scan_media_type(updates.media_type)
    if updates.enabled is not None:
        location.enabled = updates.enabled

    await db.flush()
    await db.refresh(location)

    return location


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scan_location(
    location_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a scan location."""
    result = await db.execute(
        select(ScanLocation).where(
            ScanLocation.id == location_id,
            ScanLocation.user_id == current_user.id,
        )
    )
    location = result.scalar_one_or_none()

    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scan location not found",
        )

    await db.execute(
        delete(ScanLocation).where(
            ScanLocation.id == location_id,
            ScanLocation.user_id == current_user.id,
        )
    )


# ============== Scan Operations ==============


@router.get("/status", response_model=ScanStatus)
async def get_scan_status(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Get current scan status."""
    return await scan_state_manager.get_status()


@router.post("/start", response_model=ScanStatus)
async def start_scan(
    request: ScanStartRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start a new scan."""
    # Get locations to scan
    if request.location_ids:
        requested_location_ids = set(request.location_ids)
        result = await db.execute(
            select(ScanLocation).where(
                ScanLocation.id.in_(request.location_ids),
                ScanLocation.user_id == current_user.id,
            )
        )
        requested_locations = result.scalars().all()

        if len(requested_locations) != len(requested_location_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more scan locations not found",
            )

        locations = [location for location in requested_locations if location.enabled]
    else:
        result = await db.execute(
            select(ScanLocation).where(
                ScanLocation.user_id == current_user.id,
                ScanLocation.enabled == True,
            )
        )
        locations = result.scalars().all()

    if not locations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No enabled scan locations found",
        )

    started_status = await scan_state_manager.start_scan()
    if started_status is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A scan is already in progress",
        )

    # Import here to avoid circular imports
    from app.core.scanner import run_scan

    # Start scan in background
    background_tasks.add_task(
        run_scan,
        locations=[loc.path for loc in locations],
        location_media_types={loc.path: loc.media_type for loc in locations},
        incremental=request.incremental,
        user_id=current_user.id,
        user_plex_token=current_user.plex_token,
    )

    return started_status


@router.post("/cancel", response_model=ScanStatus)
async def cancel_scan(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Cancel the current scan."""
    cancelled_status = await scan_state_manager.cancel_scan()
    if cancelled_status is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No scan is currently running",
        )

    return cancelled_status
