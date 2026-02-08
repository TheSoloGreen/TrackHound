"""Unit tests for centralized scan state transitions."""

import unittest

from app.core.scan_state import ScanStateManager


class ScanStateManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.manager = ScanStateManager()

    async def test_start_scan_transitions_to_running(self) -> None:
        started = await self.manager.start_scan(user_id=1)

        self.assertIsNotNone(started)
        self.assertTrue(started.is_running)
        self.assertEqual(started.files_scanned, 0)
        self.assertEqual(started.files_total, 0)
        self.assertFalse(await self.manager.is_cancel_requested(user_id=1))

    async def test_duplicate_start_is_rejected(self) -> None:
        first = await self.manager.start_scan(user_id=1)
        second = await self.manager.start_scan(user_id=1)

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    async def test_cancel_scan_transitions_when_running(self) -> None:
        await self.manager.start_scan(user_id=1)

        status = await self.manager.cancel_scan(user_id=1)

        self.assertIsNotNone(status)
        self.assertTrue(status.is_running)
        self.assertTrue(await self.manager.is_cancel_requested(user_id=1))

    async def test_status_updates_and_finish_scan(self) -> None:
        await self.manager.start_scan(user_id=1)
        await self.manager.update_status(
            user_id=1, current_location="/media/test", files_total=3, files_scanned=1
        )

        status = await self.manager.get_status(user_id=1)
        self.assertEqual(status.current_location, "/media/test")
        self.assertEqual(status.files_total, 3)
        self.assertEqual(status.files_scanned, 1)

        finished = await self.manager.finish_scan(user_id=1)
        self.assertFalse(finished.is_running)
        self.assertIsNone(finished.current_location)
        self.assertIsNone(finished.current_file)
        self.assertFalse(await self.manager.is_cancel_requested(user_id=1))

    async def test_user_states_are_isolated(self) -> None:
        await self.manager.start_scan(user_id=1)

        user_two_status = await self.manager.get_status(user_id=2)
        self.assertFalse(user_two_status.is_running)

        await self.manager.cancel_scan(user_id=1)
        self.assertTrue(await self.manager.is_cancel_requested(user_id=1))
        self.assertFalse(await self.manager.is_cancel_requested(user_id=2))


if __name__ == "__main__":
    unittest.main()
