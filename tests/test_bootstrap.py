from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from convo import bootstrap
from convo.core.config import user_settings_path


def test_setup_writes_private_user_settings_and_creates_loopback_container(tmp_path, monkeypatch):
    commands: list[list[str]] = []

    def fake_run(command, *, allow_failure=False):
        commands.append(command)
        return subprocess.CompletedProcess(command, 1 if "inspect" in command else 0, "", "")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(bootstrap, "_run", fake_run)
    monkeypatch.setattr(bootstrap.secrets, "token_urlsafe", lambda _size: "safe-password")

    database_url = bootstrap._ensure_container("podman", None)

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
