"""Execution-local cancellation shared with native probe threads."""

from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass, field
import threading
import time


@dataclass
class JobExecution:
    job_id: int
    user_id: int
    kind: str = "scan"
    cancelled: threading.Event = field(default_factory=threading.Event)
    last_progress_write: float = field(default_factory=time.monotonic)


current_job: ContextVar[JobExecution | None] = ContextVar("current_job", default=None)
probe_cancellation_enabled: ContextVar[bool] = ContextVar("probe_cancellation_enabled", default=True)


@contextmanager
def finish_write_verification():
    """A cancellation request must not skip analysis after a physical edit."""
    token = probe_cancellation_enabled.set(False)
    try:
        yield
    finally:
        probe_cancellation_enabled.reset(token)
