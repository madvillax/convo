"""Exercise public entry point startup with all external work replaced by fakes."""

from types import SimpleNamespace

from convo import __main__ as cli
from convo import bootstrap
from convo.core import config
from convo.core.config import Settings
from convo.pipeline import chat


def test_plain_convo_prepares_storage_before_opening_and_closes_backend(monkeypatch):
    events = []
    settings = Settings("postgresql+psycopg://test", "Qwen/Qwen3-Embedding-0.6B")
    backend = SimpleNamespace(close=lambda: events.append("closed"))
    app = SimpleNamespace(run=lambda: events.append("opened"))
    monkeypatch.setattr("sys.argv", ["convo"])
    monkeypatch.setattr(bootstrap, "ensure_storage", lambda: events.append("prepared"))
    monkeypatch.setattr(config, "load_settings", lambda: settings)
    monkeypatch.setattr(chat, "RagBackend", lambda _settings: backend)
    monkeypatch.setattr(cli, "ConvoApp", lambda *_args, **_kwargs: app)

    cli.main()

    assert events == ["prepared", "opened", "closed"]


def test_shell_preview_skips_storage_setup(monkeypatch):
    events = []
    app = SimpleNamespace(run=lambda: events.append("opened"))
    monkeypatch.setattr("sys.argv", ["convo", "--shell"])
    monkeypatch.setattr(bootstrap, "ensure_storage", lambda: events.append("prepared"))
    monkeypatch.setattr(cli, "ConvoApp", lambda *_args, **_kwargs: app)

    cli.main()

    assert events == ["opened"]
