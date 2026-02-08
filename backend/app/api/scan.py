"""Scan API endpoints for managing scan locations and running scans."""

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.models.database import get_db
from app.models.entities import User, ScanLocation
from app.models.schemas import (
    DirectoryBrowseResponse,
    DirectoryEntry,
    ScanLocationCreate,
    ScanLocationUpdate,
    ScanLocationResponse,
    ScanStatus,
    ScanStartRequest,
)

router = APIRouter()

# Global scan state with lock for thread safety
_scan_state = ScanStatus(is_running=False)
_scan_lock = asyncio.Lock()

# Root path for directory browsing (security boundary)
MEDIA_ROOT = "/media"


def get_scan_state() -> ScanStatus:
    """Get current scan state."""
    return _scan_state


def resolve_media_path(path: str) -> Path:
    """Resolve and validate a filesystem path under MEDIA_ROOT."""
    candidate = Path(path)
    if not candidate.is_absolute():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path must be absolute",
        )

    try:
        resolved = candidate.resolve()
        media_root = Path(MEDIA_ROOT).resolve()
        resolved.relative_to(media_root)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path must be under /media/",
        )
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path",
        )

    return resolved


# ============== Directory Browsing ==============


@router.get("/browse", response_model=DirectoryBrowseResponse)
async def browse_directories(
    current_user: Annotated[User, Depends(get_current_user)],
    path: str = Query(MEDIA_ROOT, description="Directory path to browse"),
):
    """List subdirectories at the given path for scan location selection."""
    resolved = resolve_media_path(path)

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
    result = await db.execute(select(ScanLocation).order_by(ScanLocation.label))
    locations = result.scalars().all()
    return locations


@router.post("/locations", response_model=ScanLocationResponse, status_code=status.HTTP_201_CREATED)
async def create_scan_location(
    location: ScanLocationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Add a new scan location."""
    resolved_path = str(resolve_media_path(location.path))

    # Check if path already exists
    result = await db.execute(
        select(ScanLocation).where(ScanLocation.path == resolved_path)
    )
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Scan location with this path already exists",
        )

    new_location = ScanLocation(
        path=resolved_path,
        label=location.label,
        media_type=location.media_type,
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
        select(ScanLocation).where(ScanLocation.id == location_id)
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
        select(ScanLocation).where(ScanLocation.id == location_id)
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
        location.media_type = updates.media_type
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
        select(ScanLocation).where(ScanLocation.id == location_id)
    )
    location = result.scalar_one_or_none()

    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scan location not found",
        )

    await db.execute(delete(ScanLocation).where(ScanLocation.id == location_id))


# ============== Scan Operations ==============


@router.get("/status", response_model=ScanStatus)
async def get_scan_status(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Get current scan status."""
    return _scan_state


@router.post("/start", response_model=ScanStatus)
async def start_scan(
    request: ScanStartRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start a new scan."""
    global _scan_state

    async with _scan_lock:
        if _scan_state.is_running:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A scan is already in progress",
            )

        # Get locations to scan
        if request.location_ids:
            result = await db.execute(
                select(ScanLocation).where(
                    ScanLocation.id.in_(request.location_ids),
                    ScanLocation.enabled == True,
                )
            )
        else:
            result = await db.execute(
                select(ScanLocation).where(ScanLocation.enabled == True)
            )

        locations = result.scalars().all()

        if not locations:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No enabled scan locations found",
            )

        # Mark as running before releasing the lock
        _scan_state.is_running = True

    # Import here to avoid circular imports
    from app.core.scanner import run_scan

    # Start scan in background
    background_tasks.add_task(
        run_scan,
        locations=[loc.path for loc in locations],
        location_media_types={loc.path: loc.media_type for loc in locations},
        incremental=request.incremental,
        user_plex_token=current_user.plex_token,
    )

    return _scan_state


@router.post("/cancel", response_model=ScanStatus)
async def cancel_scan(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Cancel the current scan."""
    global _scan_state

    if not _scan_state.is_running:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No scan is currently running",
        )

    # Import here to avoid circular imports
    from app.core.scanner import cancel_current_scan

    cancel_current_scan()

    return _scan_state
