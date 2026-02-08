"""Tests for scanner run loop argument passing and happy-path status."""

import unittest
from unittest.mock import AsyncMock, patch

from app.core.scan_state import scan_state_manager
from app.core.scanner import run_scan


class _FakeResult:
    def scalar_one_or_none(self):
        return None


class _FakeSession:
    async def execute(self, *args, **kwargs):
        return _FakeResult()

    async def scalar(self, *args, **kwargs):
        return 0

    async def commit(self):
        return None


class _FakeSessionContext:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class RunScanArgumentPassingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await scan_state_manager.reset()

    async def asyncTearDown(self) -> None:
        await scan_state_manager.reset()

    async def test_run_scan_single_file_calls_process_file_with_user_id_and_no_errors(self):
        file_path = "/media/tv/Show/Season 01/E01.mkv"

        with (
            patch("app.core.scanner.MediaScanner.discover_files", return_value=[file_path]),
            patch("app.core.scanner.MediaScanner.process_file", new_callable=AsyncMock) as process_file,
            patch("app.core.scanner.async_session_maker", return_value=_FakeSessionContext()),
        ):
            await run_scan(
                locations=["/media/tv"],
                location_media_types={"/media/tv": "tv"},
                user_id=42,
                incremental=False,
            )

        process_file.assert_awaited_once()
        process_file.assert_awaited_once_with(file_path, "/media/tv", "tv", 42, unittest.mock.ANY)

        status = await scan_state_manager.get_status()
        self.assertEqual(status.files_total, 1)
        self.assertEqual(status.files_scanned, 1)
        self.assertEqual(status.errors, [])


if __name__ == "__main__":
    unittest.main()
