"""Prepare local pgvector storage on startup and keep migrations available in wheels.

Convo manages only its labelled container and named volume. Explicit DATABASE_URL
connections are left alone at startup; ``convo --setup`` migrates them on request.
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
# Podman (including Fedora's docker shim) cannot prompt for a registry when
# startup captures subprocess output. Always use a fully qualified image name.
IMAGE = "docker.io/pgvector/pgvector:pg16"
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
    installed = []
    for candidate in ("docker", "podman"):
        if shutil.which(candidate):
            installed.append(candidate)
            if _run([candidate, "info"], allow_failure=True).returncode == 0:
                return candidate
    if installed:
        if "podman" in installed and sys.platform == "darwin":
            return "podman"
        return installed[0]
    raise SetupError(
        "Convo needs Docker Desktop or Podman to create its local PostgreSQL storage. "
        "Install one, start it, then run `convo` again."
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
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    contents = (
        "# Created by `convo --setup`. Keep this file private.\n"
        f"DATABASE_URL={database_url}\n"
        "CONVO_LOCAL_CONTAINER=1\n"
        "EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B\n"
        "RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L6-v2\n"
        "RERANK_MIN_SCORE=-3\n"
        "RETRIEVAL_CANDIDATES=20\n"
    )
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise SetupError(
            f"Settings already exist at {target}. Configure DATABASE_URL there."
        ) from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(contents)
    return target


def _configured_database_url() -> str | None:
    from convo.core.config import load_environment, load_settings

    load_environment()
    if not os.getenv("DATABASE_URL"):
        return None
    # Invalid supplied settings must be reported, never replaced by a new database.
    return load_settings().database_url


def _is_managed_database(database_url: str | None) -> bool:
    from dotenv import dotenv_values

    from convo.core.config import user_settings_path

    saved = dotenv_values(user_settings_path())
    return bool(
        database_url
        and saved.get("CONVO_LOCAL_CONTAINER") == "1"
        and saved.get("DATABASE_URL") == database_url
    )


def _ensure_container(runtime: str, database_url: str | None) -> str:
    from convo.core.config import user_settings_path

    existing = _run([runtime, "container", "inspect", CONTAINER_NAME], allow_failure=True)
    if existing.returncode == 0:
        if database_url is None:
            raise SetupError(
                f"{CONTAINER_NAME!r} already exists, but Convo has no saved database URL. "
                "Set DATABASE_URL yourself or remove that unused container manually before retrying."
            )
        label = _run(
            [
                runtime,
                "inspect",
                "--format",
                '{{index .Config.Labels "io.convo.managed"}}',
                CONTAINER_NAME,
            ]
        )
        if label.stdout.strip() != "true":
            raise SetupError(
                f"{CONTAINER_NAME!r} belongs to another setup. Set DATABASE_URL to use it explicitly."
            )
        _run([runtime, "start", CONTAINER_NAME])
        return database_url

    if database_url is not None:
        raise SetupError(
            f"Saved local storage exists but {CONTAINER_NAME!r} is missing. "
            f"Restore the container using the saved credentials and volume {VOLUME_NAME!r}."
        )
    if _run([runtime, "volume", "inspect", VOLUME_NAME], allow_failure=True).returncode == 0:
        raise SetupError(
            f"Volume {VOLUME_NAME!r} already exists without saved credentials. "
            "Restore its connection settings before starting Convo."
        )
    if user_settings_path().exists():
        raise SetupError(
            f"Settings already exist at {user_settings_path()}. Configure DATABASE_URL there."
        )
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
    local_container = _is_managed_database(configured_url)
    if configured_url is not None and not local_container:
        # An explicitly supplied DATABASE_URL may point at an existing remote or
        # shared database. Do not create a second local container around it.
        database_url = configured_url
    else:
        print("Preparing Convo's local storage…", flush=True)
        runtime = _container_runtime()
        _ensure_podman_machine(runtime)
        database_url = _ensure_container(runtime, configured_url)
        _wait_for_postgres(runtime)
    # `load_settings` reads the saved file; this assignment also supports an external DATABASE_URL.
    os.environ["DATABASE_URL"] = database_url
    try:
        _upgrade_database()
    except Exception as error:  # Alembic has several driver-specific exception classes.
        raise SetupError(
            "Could not prepare the database schema. Check PostgreSQL access and pgvector, "
            "then retry `convo --setup`."
        ) from error
    from convo.core.config import user_settings_path

    return user_settings_path()


def ensure_storage() -> None:
    """Bootstrap first use and restart managed storage before entering the TUI."""
    database_url = _configured_database_url()
    if database_url is None or _is_managed_database(database_url):
        setup()
