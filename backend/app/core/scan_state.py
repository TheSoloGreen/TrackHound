"""Centralized scan state management."""

import asyncio
from datetime import datetime, timezone

from app.models.schemas import ScanStatus


class ScanStateManager:
    """Owns scan status and cancellation state for coordination across modules."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._status = ScanStatus(is_running=False)
        self._cancel_requested = False

    async def get_status(self) -> ScanStatus:
        """Return a safe copy of the current scan status."""
        async with self._lock:
            return self._status.model_copy(deep=True)

    async def start_scan(self) -> ScanStatus | None:
        """Transition to running state, returning None if already running."""
        async with self._lock:
            if self._status.is_running:
                return None

            self._cancel_requested = False
            self._status = ScanStatus(
                is_running=True,
                current_location=None,
                files_scanned=0,
                files_total=0,
                current_file=None,
                started_at=datetime.now(timezone.utc),
                errors=[],
            )
            return self._status.model_copy(deep=True)

    async def cancel_scan(self) -> ScanStatus | None:
        """Request cancellation for a running scan."""
        async with self._lock:
            if not self._status.is_running:
                return None
            self._cancel_requested = True
            return self._status.model_copy(deep=True)

    async def is_cancel_requested(self) -> bool:
        """Check whether cancellation has been requested."""
        async with self._lock:
            return self._cancel_requested

    async def update_status(self, **kwargs) -> ScanStatus:
        """Update scan status fields and return a copy of the new state."""
        async with self._lock:
            current = self._status.model_dump()
            current.update(kwargs)
            self._status = ScanStatus(**current)
            return self._status.model_copy(deep=True)

    async def append_error(self, error: str) -> ScanStatus:
        """Append an error message to scan status."""
        async with self._lock:
            self._status.errors.append(error)
            return self._status.model_copy(deep=True)

    async def finish_scan(self) -> ScanStatus:
        """Transition to not running while keeping progress context."""
        async with self._lock:
            self._cancel_requested = False
            self._status.is_running = False
            self._status.current_location = None
            self._status.current_file = None
            return self._status.model_copy(deep=True)

    async def reset(self) -> None:
        """Reset state for tests."""
        async with self._lock:
            self._cancel_requested = False
            self._status = ScanStatus(is_running=False)


scan_state_manager = ScanStateManager()
