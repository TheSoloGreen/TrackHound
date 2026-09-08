"""Create a consistent SQLite snapshot, including committed WAL contents."""

import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3


def backup_sqlite(source: Path, destination: Path) -> None:
    source = source.resolve(strict=True)
    destination = destination.absolute()
    # Exclusive creation protects previous backups; restrictive mode protects tokens.
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(destination)) as snapshot:
                original.backup(snapshot, pages=1024)
                if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("SQLite backup failed its integrity check.")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path, help="New backup filename; existing files are never overwritten")
    arguments = parser.parse_args()
    backup_sqlite(arguments.source, arguments.destination)
    print(f"Verified SQLite backup: {arguments.destination}")


if __name__ == "__main__":
    main()
