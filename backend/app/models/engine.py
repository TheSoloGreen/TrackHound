"""Engine construction shared by the application and database integration tests."""

from sqlalchemy import event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine


def create_database_engine(url: str | URL, *, echo: bool = False):
    sqlite = make_url(url).get_backend_name() == "sqlite"
    engine = create_async_engine(
        url, echo=echo,
        connect_args={"check_same_thread": False, "timeout": 30} if sqlite else {},
    )
    if sqlite:
        @event.listens_for(engine.sync_engine, "connect")
        def configure_sqlite(connection, _record):
            # Let SQLAlchemy start real transactions, including DDL and savepoints.
            connection.isolation_level = None
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 30000")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.close()

        @event.listens_for(engine.sync_engine, "begin")
        def begin_sqlite(connection):
            mode = connection.get_execution_options().get("sqlite_transaction_mode", "")
            connection.exec_driver_sql("BEGIN IMMEDIATE" if mode == "IMMEDIATE" else "BEGIN")

    return engine
