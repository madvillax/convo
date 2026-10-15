"""Exercise real subprocess isolation without downloading model weights."""

import asyncio
import inspect
import os
import subprocess
import sys
import time

import pytest

from convo.core.config import Settings
from convo.core.contracts import Document
from convo.core.exceptions import BackendNotConnected
from convo.pipeline import worker as worker_module


def noisy_worker(connection, settings, log_path):
    worker_module._redirect_output(log_path)
    while True:
        _operation, (path,) = connection.recv()
        os.write(1, b"native stdout output\n")
        os.write(2, b"native stderr output\n")
        print("Python download output", flush=True)
        connection.send(("progress", "loading test model…"))
        if path.name == "hang.md":
            time.sleep(60)
        if path.name == "crash.md":
            os._exit(3)
        time.sleep(0.1)
        connection.send(("result", Document("test-document", path)))


@pytest.fixture
def isolated_worker(tmp_path, monkeypatch):
    script = tmp_path / "noisy_worker.py"
    script.write_text(
        "import os, sys, time\n"
        "from multiprocessing.connection import Connection\n"
        "from convo.pipeline import worker as worker_module\n"
        "from convo.core.contracts import Document\n"
        + inspect.getsource(noisy_worker)
        + "\nconnection = Connection(int(sys.argv[1]))\n"
        "settings, log_path = connection.recv()\n"
        "noisy_worker(connection, settings, log_path)\n"
    )

    def launch(child, _log_path):
        return subprocess.Popen(
            [sys.executable, str(script), str(child.fileno())],
            pass_fds=(child.fileno(),),
        )

    monkeypatch.setattr(worker_module, "_launch_worker", launch)
    monkeypatch.setattr(worker_module, "worker_log_path", lambda: tmp_path / "worker.log")
    worker = worker_module.IndexWorker(Settings("postgresql+psycopg://unused", "fake"))
    yield worker
    worker.close()


async def test_worker_captures_native_output_reports_progress_and_reuses_process(
    isolated_worker, tmp_path, capfd
):
    stages = []
    path = tmp_path / "notes.md"
    document = await isolated_worker.prepare(path, stages.append)
    process = isolated_worker._process
    assert document.path == path
    assert any("loading test model" in stage for stage in stages)
    assert any("Esc cancel" in stage for stage in stages)
    assert (await isolated_worker.prepare(path)).id == "test-document"
    assert isolated_worker._process is process
    output = capfd.readouterr()
    assert "native stdout" not in output.out
    assert "native stderr" not in output.err
    log = tmp_path / "worker.log"
    assert "native stdout" in log.read_text()
    assert "native stderr" in log.read_text()
    assert "Python download output" in log.read_text()
    assert log.stat().st_mode & 0o777 == 0o600


async def test_cancel_stops_worker_and_allows_a_fresh_preparation(isolated_worker, tmp_path):
    loading = asyncio.Event()
    task = asyncio.create_task(
        isolated_worker.prepare(
            tmp_path / "hang.md",
            lambda stage: loading.set() if "loading test model" in stage else None,
        )
    )
    await asyncio.wait_for(loading.wait(), timeout=10)
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert time.monotonic() - started < 2
    assert isolated_worker._process is None
    assert (await isolated_worker.prepare(tmp_path / "retry.md")).indexed


async def test_worker_crash_and_timeout_are_recoverable(isolated_worker, tmp_path, monkeypatch):
    with pytest.raises(BackendNotConnected, match="worker"):
        await isolated_worker.prepare(tmp_path / "crash.md")
    monkeypatch.setattr(worker_module, "PREPARE_TIMEOUT", 0.8)
    with pytest.raises(BackendNotConnected, match="timed out"):
        await isolated_worker.prepare(tmp_path / "hang.md")
    assert isolated_worker._process is None
    monkeypatch.setattr(worker_module, "PREPARE_TIMEOUT", 10)
    assert (await isolated_worker.prepare(tmp_path / "retry.md")).indexed


def test_backend_startup_does_not_import_ml_libraries_or_connect_to_storage():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from convo.pipeline.chat import RagBackend
from convo.core.config import Settings
backend = RagBackend(Settings('postgresql+psycopg://unused', 'fake'))
assert backend.documents._process is None
assert not {'torch', 'sentence_transformers', 'llama_index.core', 'numpy', 'sqlalchemy'} & sys.modules.keys()
backend.close()
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert not result.stderr
