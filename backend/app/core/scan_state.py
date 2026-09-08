"""Centralized scan state management."""

import asyncio
from datetime import datetime, timezone

from app.models.schemas import ScanStatus


class ScanStateManager:
    """Owns scan status and cancellation state for coordination across modules."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._status_by_user: dict[int, ScanStatus] = {}
        self._cancel_requested_by_user: dict[int, bool] = {}

    def _get_or_create_status(self, user_id: int) -> ScanStatus:
        if user_id not in self._status_by_user:
            self._status_by_user[user_id] = ScanStatus(is_running=False)
        return self._status_by_user[user_id]

    async def get_status(self, user_id: int) -> ScanStatus:
        """Return a safe copy of the current scan status."""
        async with self._lock:
            return self._get_or_create_status(user_id).model_copy(deep=True)

    async def start_scan(self, user_id: int) -> ScanStatus | None:
        """Transition to running state, returning None if already running."""
        async with self._lock:
            status = self._get_or_create_status(user_id)
            if status.is_running:
                return None

            self._cancel_requested_by_user[user_id] = False
            self._status_by_user[user_id] = ScanStatus(
                is_running=True,
                outcome="running",
                current_location=None,
                files_scanned=0,
                files_total=0,
                current_file=None,
                started_at=datetime.now(timezone.utc),
                errors=[],
            )
            return self._status_by_user[user_id].model_copy(deep=True)

    async def cancel_scan(self, user_id: int) -> ScanStatus | None:
        """Request cancellation for a running scan."""
        async with self._lock:
            status = self._get_or_create_status(user_id)
            if not status.is_running:
                return None
            self._cancel_requested_by_user[user_id] = True
            return status.model_copy(deep=True)

    async def is_cancel_requested(self, user_id: int) -> bool:
        """Check whether cancellation has been requested."""
        async with self._lock:
            return self._cancel_requested_by_user.get(user_id, False)

    async def update_status(self, user_id: int, **kwargs) -> ScanStatus:
        """Update scan status fields and return a copy of the new state."""
        async with self._lock:
            status = self._get_or_create_status(user_id)
            current = status.model_dump()
            current.update(kwargs)
            self._status_by_user[user_id] = ScanStatus(**current)
            return self._status_by_user[user_id].model_copy(deep=True)

    async def append_error(self, user_id: int, error: str) -> ScanStatus:
        """Append an error message to scan status."""
        async with self._lock:
            status = self._get_or_create_status(user_id)
            status.error_count += 1
            if len(status.errors) < 50:
                status.errors.append(error)
            return status.model_copy(deep=True)

    async def append_warning(self, user_id: int, warning: str) -> ScanStatus:
        async with self._lock:
            status = self._get_or_create_status(user_id)
            status.warning_count += 1
            if len(status.warnings) < 50:
                status.warnings.append(warning)
            return status.model_copy(deep=True)

    async def finish_scan(self, user_id: int, *, failed: bool = False) -> ScanStatus:
        """Transition to not running while keeping progress context."""
        async with self._lock:
            status = self._get_or_create_status(user_id)
            cancelled = self._cancel_requested_by_user.get(user_id, False)
            status.outcome = ("failed" if failed else "cancelled" if cancelled else
                              "completed_with_errors" if status.error_count or status.warning_count else "completed")
            status.finished_at = datetime.now(timezone.utc)
            self._cancel_requested_by_user[user_id] = False
            status.is_running = False
            status.current_location = None
            status.current_file = None
            return status.model_copy(deep=True)

    async def reset(self) -> None:
        """Reset state for tests."""
        async with self._lock:
            self._cancel_requested_by_user = {}
            self._status_by_user = {}


scan_state_manager = ScanStateManager()
