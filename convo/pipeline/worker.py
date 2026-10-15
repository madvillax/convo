"""Keep ML imports, downloads, native output and cancellable work outside the TUI."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import subprocess
import sys
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from typing import cast

from convo.core.config import Settings
from convo.core.contracts import Document, Hit
from convo.core.exceptions import BackendNotConnected

PREPARE_TIMEOUT = 15 * 60
SEARCH_TIMEOUT = 120


def worker_log_path() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "convo" / "rag-worker.log"


def _redirect_output(path: Path) -> None:
    """Capture even native-library writes, which redirect_stdout cannot intercept."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.dup2(descriptor, 1)
        os.dup2(descriptor, 2)
    finally:
        os.close(descriptor)
    logging.basicConfig(level=logging.WARNING, force=True)


def _launch_worker(child: Connection, log_path: Path) -> subprocess.Popen[bytes]:
    # Capture output from process creation onwards, including descendant resource
    # trackers. No fork of the running Textual/Torch event loop is involved.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "ab") as log:
        os.fchmod(log.fileno(), 0o600)
        return subprocess.Popen(
            [sys.executable, "-m", "convo.pipeline.worker", str(child.fileno())],
            pass_fds=(child.fileno(),),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
        )


def _serve(connection: Connection, settings: Settings, log_path: Path) -> None:
    """Spawn entry point: no ML package is imported in the parent process."""
    try:
        _redirect_output(log_path)
        os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")
        from convo.pipeline.index import DocumentIndex

        index = DocumentIndex(settings)
        index.progress = lambda stage: connection.send(("progress", stage))

        async def serve() -> None:
            try:
                while True:
                    operation, arguments = connection.recv()
                    try:
                        if operation == "prepare":
                            result = await index.prepare(*arguments)
                        else:
                            result = await index.search(*arguments)
                        connection.send(("result", result))
                    except BackendNotConnected as error:
                        connection.send(("error", str(error)))
                    except Exception:
                        logging.exception("RAG %s failed", operation)
                        connection.send(
                            (
                                "error",
                                f"Could not {operation} the file. Details: {log_path}. "
                                "Check the file and database, then retry /file.",
                            )
                        )
            finally:
                index.close()

        asyncio.run(serve())
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        logging.exception("RAG worker failed")
        try:
            connection.send(("error", f"RAG worker could not start. Details: {log_path}"))
        except (EOFError, BrokenPipeError, OSError):
            pass
    finally:
        connection.close()


class IndexWorker:
    """One reusable process retains loaded Qwen weights until exit or cancellation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._process: subprocess.Popen[bytes] | None = None
        self._connection: Connection | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    def _start(self) -> Connection:
        if self._closed:
            raise RuntimeError("Document worker is closed")
        if self._process is None or self._process.poll() is not None:
            self._stop()
            connection, child = multiprocessing.Pipe()
            try:
                process = _launch_worker(child, worker_log_path())
                self._process, self._connection = process, connection
                connection.send((self.settings, worker_log_path()))
            except BaseException:
                connection.close()
                self._stop()
                raise
            finally:
                child.close()
        assert self._connection is not None
        return self._connection

    async def _request(
        self,
        operation: str,
        arguments: tuple[object, ...],
        timeout: float,
        progress: Callable[[str], None] | None = None,
    ) -> object:
        async with self._lock:
            connection = self._start()
            started = time.monotonic()
            stage = "starting file worker…"
            last_status = ""
            try:
                connection.send((operation, arguments))
                while True:
                    elapsed = time.monotonic() - started
                    if elapsed > timeout:
                        raise BackendNotConnected(
                            f"File operation timed out after {int(timeout)}s. "
                            f"Check your connection and {worker_log_path()}, then retry /file."
                        )
                    if connection.poll():
                        kind, value = connection.recv()
                        if kind == "result":
                            return value
                        if kind == "error":
                            raise BackendNotConnected(value)
                        stage = value
                    status = f"{stage} {int(elapsed)}s" + (
                        " · Esc cancel" if operation == "prepare" else ""
                    )
                    if progress and status != last_status:
                        progress(status)
                        last_status = status
                    if self._process is None or self._process.poll() is not None:
                        raise BackendNotConnected(
                            f"File worker stopped unexpectedly. Details: {worker_log_path()}. "
                            "Retry /file; close other apps if memory is low."
                        )
                    await asyncio.sleep(0.05)
            except (EOFError, BrokenPipeError, OSError) as error:
                self._stop()
                raise BackendNotConnected(
                    f"Lost the file worker. Details: {worker_log_path()}. Retry /file."
                ) from error
            except BaseException:
                # Unlike a thread, terminating this process stops imports/downloads/inference.
                # PostgreSQL rolls back any uncommitted writes on connection loss.
                self._stop()
                raise

    async def prepare(self, path: Path, progress: Callable[[str], None] | None = None) -> Document:
        return cast(Document, await self._request("prepare", (path,), PREPARE_TIMEOUT, progress))

    async def search(
        self, document: Document, question: str, progress: Callable[[str], None] | None = None
    ) -> list[Hit]:
        return cast(
            list[Hit], await self._request("search", (document, question), SEARCH_TIMEOUT, progress)
        )

    def _stop(self, *, graceful: bool = False) -> None:
        process, self._process = self._process, None
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if process is not None:
            if graceful:
                try:
                    process.wait(timeout=1)
                    return
                except subprocess.TimeoutExpired:
                    pass
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)

    def close(self) -> None:
        self._closed = True
        self._stop(graceful=True)


if __name__ == "__main__":
    pipe = Connection(int(sys.argv[1]))
    worker_settings, worker_log = pipe.recv()
    _serve(pipe, worker_settings, worker_log)
