"""Exercise WAL contention with a real independent writer, not a mocked lock."""
import sqlite3
from unittest.mock import patch

import pytest
from sqlalchemy import event, select, func
from sqlalchemy.exc import OperationalError

from app.core import scanner as scanning
from app.core.scan_state import scan_state_manager
from app.models.entities import MediaFile
from test_scanner_run_scan import library, write_media, run, files, ENGLISH


@pytest.mark.asyncio
async def test_wal_snapshot_conflict_retries_file_once_and_continues(library):
    write_media(library.root)
    write_media(library.root, "Other/Season 01/E02.mkv")
    engine = library.sessions.kw['bind']
    conflicts = []

    def competing_write(_connection, _cursor, statement, *_):
        if not conflicts and statement.startswith('INSERT INTO shows'):
            # The scanner already read its snapshot. Commit a real independent
            # writer before it upgrades that snapshot to a write transaction.
            with sqlite3.connect(engine.url.database) as writer:
                writer.execute("UPDATE users SET plex_username='concurrent writer'")
            conflicts.append(True)

    event.listen(engine.sync_engine, 'before_cursor_execute', competing_write)
    try:
        with patch.object(scanning.AudioAnalyzer, 'analyze', return_value=ENGLISH) as probe:
            status = await run(library)
        assert conflicts == [True]
        assert status.outcome == 'completed'
        assert status.error_count == 0 and status.files_scanned == 2
        assert probe.call_count == 2  # one probe per file, including the retry
        assert len(await files(library)) == 2
    finally:
        event.remove(engine.sync_engine, 'before_cursor_execute', competing_write)


def locked():
    error = sqlite3.OperationalError('database is locked')
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    return OperationalError('COMMIT', {}, error)


@pytest.mark.asyncio
async def test_commit_retry_does_not_repeat_physical_edit(library):
    source = write_media(library.root)
    scanner = scanning.MediaScanner()
    async with library.sessions() as db:
        commit = db.commit
        attempts = 0
        async def fail_first_commit():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise locked()
            await commit()
        with patch.object(db, 'commit', side_effect=fail_first_commit), patch.object(scanner, '_auto_fix_default_track', return_value=ENGLISH) as edit:
            assert await scanner.process_file(str(source), str(library.root), 'tv', library.user.id, db, incremental=False, managed=True)
        assert attempts == 2
        edit.assert_called_once()
        assert await db.scalar(select(func.count(MediaFile.id))) == 1


@pytest.mark.asyncio
async def test_exhausted_retries_report_path_and_do_not_reconcile(library):
    source = write_media(library.root)
    with patch.object(scanning.MediaScanner, '_process_file', side_effect=locked()) as persist:
        status = await run(library)
    assert persist.call_count == 4
    assert status.outcome == 'completed_with_errors'
    assert status.files_removed == 0
    assert str(source) in status.errors[0] and 'after retries' in status.errors[0]


@pytest.mark.asyncio
async def test_cancellation_stops_retries(library):
    write_media(library.root)
    async def cancel_and_fail(*_args):
        await scan_state_manager.cancel_scan(library.user.id)
        raise locked()
    with patch.object(scanning.MediaScanner, '_process_file', side_effect=cancel_and_fail) as persist:
        status = await run(library)
    assert persist.call_count == 1
    assert status.outcome == 'cancelled'


@pytest.mark.asyncio
async def test_analysis_errors_are_not_retried(library):
    write_media(library.root)
    with patch.object(scanning.AudioAnalyzer, 'analyze', side_effect=ValueError('bad probe')) as probe:
        status = await run(library)
    probe.assert_called_once()
    assert status.error_count == 1
