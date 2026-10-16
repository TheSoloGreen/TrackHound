"""Kill and reap actual disposable processes, not just mocked timeouts."""

import asyncio
import subprocess
import sys

import pytest

from app.core import analyzer
from app.core.job_context import JobExecution, current_job


@pytest.fixture
def sleeping_probe(monkeypatch):
    real_popen = subprocess.Popen
    children = []

    def start(*_, **kwargs):
        process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(analyzer.subprocess, "Popen", start)
    return children


def test_probe_deadline_kills_and_reaps_child(sleeping_probe, monkeypatch):
    monkeypatch.setattr(analyzer, "PROBE_TIMEOUT_SECONDS", 0.1)
    with pytest.raises(analyzer.AudioAnalysisError, match="deadline"):
        analyzer.AudioAnalyzer().analyze("/disposable.mkv")
    assert sleeping_probe[0].poll() is not None


@pytest.mark.asyncio
async def test_cancellation_interrupts_probe_without_blocking_loop(sleeping_probe):
    execution = JobExecution(1, 1)
    token = current_job.set(execution)
    try:
        task = asyncio.create_task(asyncio.to_thread(analyzer.AudioAnalyzer().analyze, "/disposable.mkv"))
        for _ in range(100):
            if sleeping_probe:
                break
            await asyncio.sleep(0.01)
        execution.cancelled.set()
        with pytest.raises(analyzer.AudioAnalysisError, match="cancelled"):
            await asyncio.wait_for(task, timeout=3)
        assert sleeping_probe[0].poll() is not None
    finally:
        current_job.reset(token)
