"""Create Convo's opt-in local pgvector storage without shelling out through a shell.

The normal application never creates containers.  This module runs only for the
explicit ``convo --setup`` command (or the separately invoked install script).
It uses a named volume and binds PostgreSQL to loopback only.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import time
from importlib.resources import as_file, files
from pathlib import Path
from urllib.parse import quote

CONTAINER_NAME = "convo-postgres"
VOLUME_NAME = "convo-postgres-data"
IMAGE = "pgvector/pgvector:pg16"
DATABASE_NAME = "convo"
DATABASE_USER = "convo"


class SetupError(RuntimeError):
    """The machine cannot safely complete the requested local setup."""


def _run(command: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError as error:
        raise SetupError(f"Could not run {command[0]!r}: {error}") from error
    if result.returncode and not allow_failure:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise SetupError(f"{' '.join(command[:2])} failed: {detail}")
    return result


def _container_runtime() -> str:
    for candidate in ("docker", "podman"):
        if shutil.which(candidate):
            return candidate
    raise SetupError(
        "Convo needs Docker Desktop or Podman to create its local PostgreSQL storage. "
        "Install one, start it, then run `convo --setup` again."
    )


def _ensure_podman_machine(runtime: str) -> None:
    """Start Podman's macOS VM when it exists; leave other platforms untouched."""
    if runtime != "podman" or sys.platform != "darwin":
        return
    if _run([runtime, "info"], allow_failure=True).returncode == 0:
        return
    machines = _run([runtime, "machine", "list", "--format", "{{.Name}}"], allow_failure=True)
    if machines.returncode:
        raise SetupError(
            "Podman is installed but unavailable. Start Podman, then run `convo --setup`."
        )
    if not machines.stdout.strip():
        _run([runtime, "machine", "init"])
    _run([runtime, "machine", "start"])


def _write_local_settings(database_url: str) -> Path:
    from convo.core.config import user_settings_path

    target = user_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# Created by `convo --setup`. Keep this file private.\n"
        f"DATABASE_URL={database_url}\n"
        "CONVO_LOCAL_CONTAINER=1\n"
        "EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B\n"
        "RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L6-v2\n"
        "RERANK_MIN_SCORE=-3\n"
        "RETRIEVAL_CANDIDATES=20\n",
        encoding="utf-8",
    )
    target.chmod(0o600)
    return target


def _configured_database_url() -> str | None:
    from convo.core.config import load_settings

    try:
        return load_settings().database_url
    except ValueError:
        return None


def _ensure_container(runtime: str, database_url: str | None) -> str:
    existing = _run([runtime, "container", "inspect", CONTAINER_NAME], allow_failure=True)
    if existing.returncode == 0:
        _run([runtime, "start", CONTAINER_NAME], allow_failure=True)
        if database_url is None:
            raise SetupError(
                f"{CONTAINER_NAME!r} already exists, but Convo has no saved database URL. "
                "Set DATABASE_URL yourself or remove that unused container manually before retrying."
            )
        return database_url

    password = secrets.token_urlsafe(24)
    database_url = (
        f"postgresql+psycopg://{DATABASE_USER}:{quote(password, safe='')}"
        f"@localhost:5432/{DATABASE_NAME}"
    )
    _run(
        [
            runtime,
            "run",
            "--name",
            CONTAINER_NAME,
            "--label",
            "io.convo.managed=true",
            "-e",
            f"POSTGRES_USER={DATABASE_USER}",
            "-e",
            f"POSTGRES_PASSWORD={password}",
            "-e",
            f"POSTGRES_DB={DATABASE_NAME}",
            "-p",
            "127.0.0.1:5432:5432",
            "-v",
            f"{VOLUME_NAME}:/var/lib/postgresql/data",
            "-d",
            IMAGE,
        ]
    )
    _write_local_settings(database_url)
    return database_url


def _wait_for_postgres(runtime: str) -> None:
    for _attempt in range(30):
        ready = _run(
            [
                runtime,
                "exec",
                CONTAINER_NAME,
                "pg_isready",
                "-U",
                DATABASE_USER,
                "-d",
                DATABASE_NAME,
            ],
            allow_failure=True,
        )
        if ready.returncode == 0:
            return
        time.sleep(1)
    raise SetupError("PostgreSQL did not become ready within 30 seconds. Check the container logs.")


def _migration_directory() -> Path | None:
    from convo.core.config import PROJECT_ROOT

    source_directory = PROJECT_ROOT / "migrations"
    if source_directory.is_dir():
        return source_directory
    return None


def _upgrade_database() -> None:
    from alembic import command
    from alembic.config import Config

    migration_directory = _migration_directory()
    if migration_directory is not None:
        config = Config()
        config.set_main_option("script_location", str(migration_directory))
        command.upgrade(config, "head")
        return
    # Hatch copies the source migration tree into the installed package. Keep
    # `as_file` open while Alembic reads scripts for zip-safe resource access.
    with as_file(files("convo").joinpath("migrations")) as packaged_directory:
        config = Config()
        config.set_main_option("script_location", str(packaged_directory))
        command.upgrade(config, "head")


def setup() -> Path:
    """Provision local storage or migrate an explicitly configured PostgreSQL database."""
    configured_url = _configured_database_url()
    local_container = os.getenv("CONVO_LOCAL_CONTAINER") == "1"
    if configured_url is not None and not local_container:
        # An explicitly supplied DATABASE_URL may point at an existing remote or
        # shared database. Do not create a second local container around it.
        database_url = configured_url
    else:
        runtime = _container_runtime()
        _ensure_podman_machine(runtime)
        database_url = _ensure_container(runtime, configured_url)
        _wait_for_postgres(runtime)
    # `load_settings` reads the saved file; this assignment also supports an external DATABASE_URL.
    os.environ["DATABASE_URL"] = database_url
    try:
        _upgrade_database()
    except Exception as error:  # Alembic has several driver-specific exception classes.
        raise SetupError(f"Database was created but migrations failed: {error}") from error
    from convo.core.config import user_settings_path

    return user_settings_path()
