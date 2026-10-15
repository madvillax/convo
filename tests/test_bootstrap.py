from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from convo import bootstrap
from convo.core import config
from convo.core.config import user_settings_path


@pytest.mark.parametrize("runtime", ["docker", "podman"])
def test_setup_writes_private_user_settings_and_creates_loopback_container(
    tmp_path, monkeypatch, runtime
):
    commands: list[list[str]] = []

    def fake_run(command, *, allow_failure=False):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1 if "inspect" in command else 0, "", "")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(bootstrap, "_run", fake_run)
    monkeypatch.setattr(bootstrap.secrets, "token_urlsafe", lambda _size: "safe-password")

    database_url = bootstrap._ensure_container(runtime, None)

    assert database_url == "postgresql+psycopg://convo:safe-password@localhost:5432/convo"
    assert user_settings_path().read_text(encoding="utf-8") == (
        "# Created by `convo --setup`. Keep this file private.\n"
        "DATABASE_URL=postgresql+psycopg://convo:safe-password@localhost:5432/convo\n"
        "CONVO_LOCAL_CONTAINER=1\n"
        "EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B\n"
        "RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L6-v2\n"
        "RERANK_MIN_SCORE=-3\n"
        "RETRIEVAL_CANDIDATES=20\n"
    )
    assert user_settings_path().stat().st_mode & 0o777 == 0o600
    create_command = next(command for command in commands if command[1] == "run")
    # Both Podman and its Docker-compatible shim must avoid interactive
    # short-name registry resolution on distributions such as Fedora.
    assert create_command[0] == runtime
    assert create_command[-1] == "docker.io/pgvector/pgvector:pg16"
    assert "127.0.0.1:5432:5432" in create_command
    assert "convo-postgres-data:/var/lib/postgresql/data" in create_command
    assert "io.convo.managed=true" in create_command


def test_existing_container_never_infers_or_overwrites_its_password(monkeypatch):
    def fake_run(command, *, allow_failure=False):
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(bootstrap, "_run", fake_run)

    with pytest.raises(bootstrap.SetupError, match="already exists"):
        bootstrap._ensure_container("docker", None)


def test_setup_uses_explicit_database_url_without_creating_a_container(monkeypatch):
    expected = "postgresql+psycopg://reader:secret@example.test/convo"
    monkeypatch.setattr(bootstrap, "_configured_database_url", lambda: expected)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CONVO_LOCAL_CONTAINER", raising=False)
    monkeypatch.setattr(
        bootstrap, "_container_runtime", lambda: pytest.fail("runtime should not run")
    )
    monkeypatch.setattr(bootstrap, "_upgrade_database", lambda: None)
    monkeypatch.setattr("convo.core.config.user_settings_path", lambda: Path("/tmp/convo"))

    assert bootstrap.setup().as_posix() == "/tmp/convo"


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "checkout")
    for name in (
        "DATABASE_URL",
        "CONVO_LOCAL_CONTAINER",
        "EMBEDDING_MODEL",
        "RERANKER_MODEL",
        "RERANK_MIN_SCORE",
        "RETRIEVAL_CANDIDATES",
    ):
        monkeypatch.delenv(name, raising=False)


def test_first_launch_creates_storage_then_later_launch_reuses_it(isolated_config, monkeypatch):
    created = False
    starts = []
    migrations = []

    def fake_run(command, *, allow_failure=False):
        nonlocal created
        if command[1:3] == ["container", "inspect"]:
            return subprocess.CompletedProcess(command, 0 if created else 1, "", "")
        if command[1:3] == ["volume", "inspect"]:
            return subprocess.CompletedProcess(command, 1, "", "")
        if command[1] == "run":
            created = True
        if command[1] == "start":
            starts.append(command[-1])
        return subprocess.CompletedProcess(command, 0, "true\n", "")

    monkeypatch.setattr(bootstrap, "_run", fake_run)
    monkeypatch.setattr(bootstrap, "_container_runtime", lambda: "docker")
    monkeypatch.setattr(bootstrap, "_upgrade_database", lambda: migrations.append("head"))

    bootstrap.ensure_storage()
    first_url = config.load_settings().database_url
    bootstrap.ensure_storage()

    assert config.load_settings().database_url == first_url
    assert starts == [bootstrap.CONTAINER_NAME]
    assert migrations == ["head", "head"]


def test_external_url_override_does_not_restart_or_migrate_local_storage(
    isolated_config, monkeypatch
):
    bootstrap._write_local_settings("postgresql+psycopg://convo:secret@localhost:5432/convo")
    remote_url = "postgresql+psycopg://reader:secret@example.test/convo"
    monkeypatch.setenv("DATABASE_URL", remote_url)
    monkeypatch.setattr(bootstrap, "setup", lambda: pytest.fail("setup should not run"))

    bootstrap.ensure_storage()

    assert config.load_settings().database_url == remote_url


def test_invalid_database_settings_do_not_trigger_automatic_setup(isolated_config, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "invalid-url")
    monkeypatch.setattr(bootstrap, "setup", lambda: pytest.fail("setup should not run"))

    with pytest.raises(ValueError, match="DATABASE_URL"):
        bootstrap.ensure_storage()


def test_config_write_preserves_existing_settings(isolated_config):
    target = bootstrap._write_local_settings("postgresql+psycopg://original")
    original = target.read_bytes()

    with pytest.raises(bootstrap.SetupError, match="Settings already exist"):
        bootstrap._write_local_settings("postgresql+psycopg://replacement")

    assert target.read_bytes() == original
