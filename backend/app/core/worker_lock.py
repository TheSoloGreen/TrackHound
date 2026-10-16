"""Lifetime lock: refuse a second app worker before recovery can touch jobs."""

from pathlib import Path
import sys

from sqlalchemy import text

LOCK_ID = 752142981076  # Stable TrackHound-specific PostgreSQL advisory lock.


class WorkerLock:
    def __init__(self, engine):
        self.engine = engine
        self.connection = None
        self.file = None

    async def acquire(self):
        if self.engine.dialect.name == "postgresql":
            self.connection = await self.engine.connect()
            try:
                acquired = await self.connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_ID})
                await self.connection.commit()
                if not acquired:
                    raise RuntimeError("TrackHound already has an active worker. Run one application process per database.")
            except BaseException:
                await self.connection.close()
                self.connection = None
                raise
            return
        database = self.engine.url.database
        if not database or database == ":memory:":
            return
        path = Path(database).resolve()
        self.file = path.with_name(path.name + ".worker.lock").open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt
                if self.file.tell() == 0:
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise RuntimeError("TrackHound already has an active worker. Run one application process per database.") from exc

    async def release(self):
        if self.connection:
            try:
                await self.connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_ID})
                await self.connection.commit()
            finally:
                await self.connection.close()
                self.connection = None
        if self.file:
            # Closing releases the OS lock. Do not unlink: another process may
            # already have this inode open while waiting to acquire its lock.
            self.file.close()
            self.file = None
