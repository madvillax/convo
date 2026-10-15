import asyncio

from textual.widgets import Input, OptionList, Static

from convo.core.contracts import Answer, ChatModel, Document, GenerationSelection, Source
from convo.core.exceptions import BackendNotConnected
from convo.ui.app import ConvoApp
from convo.ui.commands import COMMANDS, CommandMenu
from convo.ui.files import FilePicker
from convo.ui.models import ModelPicker
from convo.ui.preview import ShellBackend


async def submit(app, pilot, value):
    app.query_one("#prompt", Input).value = value
    await pilot.press("enter")
    await pilot.pause()


async def test_picker_and_shell_are_honest(tmp_path):
    (tmp_path / "notes.md").write_text("A small document")
    (tmp_path / ".secret.txt").write_text("private")
    (tmp_path / "image.png").write_bytes(b"png")
    app = ConvoApp(tmp_path, ShellBackend())
    async with app.run_test(size=(100, 30)) as pilot:
        await submit(app, pilot, "/file")
        assert isinstance(app.screen, FilePicker)
        app.screen.query_one("#file-search", Input).value = "notes"
        await pilot.pause()
        assert [p.name for p in app.screen.entries] == ["notes.md"]
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.document is not None
        assert app.document.path == tmp_path / "notes.md"
        assert not app.document.indexed
        await submit(app, pilot, "What does it say?")
        await app.workers.wait_for_complete()
        assert not app.history
        assert not app.busy
        assert "Shell preview only" in str(list(app.query(".message"))[-1].render())


class TestBackend:
    __test__ = False

    def __init__(self):
        self.calls = []

    async def prepare(self, path):
        return Document(str(path), path)

    async def answer(self, document, question, history):
        self.calls.append((document, question, history))
        await asyncio.sleep(0.01)
        if question == "fail":
            raise RuntimeError("secret-token")
        return Answer("The answer is here [1].", (Source("notes.md · lines 1–2", "A fact"),))


class AccountBackend(TestBackend):
    async def login_openai(self):
        return "reader@example.com"


async def test_login_command(tmp_path):
    backend = AccountBackend()
    app = ConvoApp(tmp_path, backend)
    async with app.run_test(size=(80, 24)) as pilot:
        await submit(app, pilot, "/login")
        await app.workers.wait_for_complete()
        assert "reader@example.com" in str(list(app.query(".message"))[-1].render())
        assert not app.busy


async def test_backend_boundary_switch_clear_and_error(tmp_path):
    first = tmp_path / "first.md"
    first.write_text("First")
    second = tmp_path / "second.md"
    second.write_text("Second")
    backend = TestBackend()
    app = ConvoApp(tmp_path, backend)
    async with app.run_test(size=(80, 24)) as pilot:
        app.file_chosen(first)
        await app.workers.wait_for_complete()
        await submit(app, pilot, "Question one")
        await app.workers.wait_for_complete()
        await submit(app, pilot, "Question two")
        await app.workers.wait_for_complete()
        assert backend.calls[0][2] == ()
        assert len(backend.calls[1][2]) == 2
        assert len(app.history) == 4
        assert "notes.md · lines 1–2" in str(list(app.query(".message"))[-1].render())
        await submit(app, pilot, "fail")
        await app.workers.wait_for_complete()
        assert len(app.history) == 4
        assert "secret-token" not in str(list(app.query(".message"))[-1].render())
        app.file_chosen(second)
        await app.workers.wait_for_complete()
        assert app.document is not None
        assert app.document.path == second
        assert app.history == ()
        await submit(app, pilot, "/clear")
        assert app.document is not None
        assert app.document.path == second
        await submit(app, pilot, "/reset")
        assert app.document is None


async def test_nested_picker_cancel_and_small_terminal(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "inside.txt").write_text("Hello")
    (tmp_path / "escape.txt").symlink_to("/etc/hosts")
    app = ConvoApp(tmp_path, ShellBackend())
    async with app.run_test(size=(50, 18)) as pilot:
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, FilePicker)
        assert len(app.screen.entries) == 1
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, FilePicker)
        assert app.screen.folder == folder
        options = app.screen.query_one("#file-options", OptionList)
        options.highlighted = 1
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.document is not None
        assert app.document.path.name == "inside.txt"
        await pilot.press("ctrl+o", "escape")
        await pilot.pause()
        assert app.document is not None
        assert app.document.path.name == "inside.txt"
        assert app.query_one("#prompt", Input).region.width > 0
        assert app.query_one("#status", Static).region.y < 18


class GenerationBackend(AccountBackend):
    def __init__(self):
        super().__init__()
        self.logged_in = False
        self.selection = GenerationSelection()
        self.models = (
            ChatModel("model-alpha", "Alpha", ("low", "medium", "high")),
            ChatModel("model-beta", "Beta", ("low", "high")),
            ChatModel("model-auto", "Automatic"),
        )
        self.generation_calls = []

    async def login_openai(self):
        self.logged_in = True
        self.selection = GenerationSelection(connected=True)
        return "reader@example.com"

    def generation_selection(self):
        return self.selection

    async def list_models(self):
        if not self.logged_in:
            raise BackendNotConnected("Connect your ChatGPT account with /login")
        if self.selection.model is None:
            self.selection = GenerationSelection(self.models[0], connected=True)
        return self.models

    async def select_model(self, model_id):
        await self.list_models()
        model = next(model for model in self.models if model.id == model_id)
        effort = self.selection.reasoning_effort
        self.selection = GenerationSelection(
            model, effort if effort in model.reasoning_efforts else None, connected=True
        )
        return self.selection

    async def cycle_reasoning(self):
        await self.list_models()
        model = self.selection.model
        assert model is not None
        choices = (None, *model.reasoning_efforts)
        effort = choices[(choices.index(self.selection.reasoning_effort) + 1) % len(choices)]
        self.selection = GenerationSelection(model, effort, connected=True)
        return self.selection

    async def answer(self, document, question, history):
        self.generation_calls.append(self.selection)
        return await super().answer(document, question, history)


async def test_slash_menu_typing_navigation_completion_and_escape(tmp_path):
    backend = GenerationBackend()
    app = ConvoApp(tmp_path, backend)
    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.press("/")
        menu = app.query_one("#command-menu", CommandMenu)
        prompt = app.query_one("#prompt", Input)
        assert menu.display
        assert [choice.name for choice in app.command_choices] == [entry.name for entry in COMMANDS]
        await pilot.press("down", "down")
        assert menu.highlighted == 2
        assert prompt.has_focus
        await pilot.press("tab")
        assert prompt.value == "/models"
        await pilot.press("escape")
        assert not menu.display
        assert prompt.value == "/models"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        assert "/login" in str(list(app.query(".message"))[-1].render())
        assert not app.busy
        prompt.value = "/mo"
        await pilot.pause()
        assert [choice.name for choice in app.command_choices] == ["/models"]
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        assert not app.busy
        assert prompt.has_focus

        prompt.value = "/"
        await pilot.pause()
        await pilot.press("down", "enter")
        await app.workers.wait_for_complete()
        assert backend.logged_in


async def test_model_picker_thinking_and_actual_answer_selection(tmp_path):
    backend = GenerationBackend()
    app = ConvoApp(tmp_path, backend)
    async with app.run_test(size=(90, 30)) as pilot:
        await submit(app, pilot, "/login")
        await app.workers.wait_for_complete()
        assert "Alpha" in str(app.query_one("#selection", Static).render())
        prompt = app.query_one("#prompt", Input)
        prompt.value = "keep this question"
        await pilot.press("shift+tab")
        await app.workers.wait_for_complete()
        assert prompt.value == "keep this question"
        assert prompt.has_focus
        assert app.selection.reasoning_effort == "low"
        assert "thinking low" in str(app.query_one("#thinking", Static).render())
        await submit(app, pilot, "/models")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, ModelPicker)
        search = app.screen.query_one("#model-search", Input)
        await pilot.press("down")
        assert app.screen.query_one("#model-options", OptionList).highlighted == 1
        # Shift+Tab inside the picker keeps its normal focus behavior.
        await pilot.press("shift+tab")
        assert app.selection.reasoning_effort == "low"
        search.focus()
        search.value = "beta"
        await pilot.pause()
        assert len(app.screen.entries) == 1
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not isinstance(app.screen, ModelPicker)
        assert app.selection.model.id == "model-beta"
        assert "Beta" in str(app.query_one("#selection", Static).render())
        assert app.selection.reasoning_effort == "low"
        await pilot.press("shift+tab")
        await app.workers.wait_for_complete()
        assert app.selection.reasoning_effort == "high"
        selected_file = tmp_path / "notes.md"
        selected_file.write_text("a fact")
        app.file_chosen(selected_file)
        await app.workers.wait_for_complete()
        await submit(app, pilot, "Question with selected settings")
        await app.workers.wait_for_complete()
        assert backend.generation_calls[-1].model.id == "model-beta"
        assert backend.generation_calls[-1].reasoning_effort == "high"
        await submit(app, pilot, "/clear")
        assert app.selection.reasoning_effort == "high"


async def test_small_terminal_menu_picker_cancel_and_empty_filter(tmp_path):
    backend = GenerationBackend()
    app = ConvoApp(tmp_path, backend)
    async with app.run_test(size=(50, 18)) as pilot:
        await pilot.press("/")
        await pilot.pause()
        for widget_id in ("prompt", "selection", "status", "keys"):
            region = app.query_one(f"#{widget_id}").region
            assert region.y >= 0
            assert region.bottom <= 18
        await pilot.resize_terminal(100, 32)
        await pilot.resize_terminal(50, 18)
        await pilot.pause()
        assert app.query_one("#prompt", Input).region.bottom <= 18
        assert app.query_one("#thinking", Static).region.bottom <= 18
        await pilot.press("escape")
        await submit(app, pilot, "/login")
        await app.workers.wait_for_complete()
        await submit(app, pilot, "/models")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(app.screen, ModelPicker)
        before = app.selection
        app.screen.query_one("#model-search", Input).value = "no-such-model"
        await pilot.pause()
        assert not app.screen.entries
        await pilot.press("enter")
        assert isinstance(app.screen, ModelPicker)
        await pilot.press("escape")
        assert app.selection == before
        await submit(app, pilot, "/models model-auto")
        await app.workers.wait_for_complete()
        await pilot.press("shift+tab")
        await app.workers.wait_for_complete()
        assert app.selection.reasoning_effort is None
        assert not app.busy


async def test_file_picker_arrows_move_on_first_press_and_filter_stays_focused(tmp_path):
    (tmp_path / "a.txt").write_text("first")
    (tmp_path / "b.txt").write_text("second")
    app = ConvoApp(tmp_path, ShellBackend())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, FilePicker)
        await pilot.press("down")
        assert app.screen.query_one("#file-options", OptionList).highlighted == 1
        assert app.screen.query_one("#file-search", Input).has_focus
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        assert app.document.path.name == "b.txt"


async def test_saved_model_and_effort_restore_on_startup(tmp_path):
    backend = GenerationBackend()
    backend.logged_in = True
    backend.selection = GenerationSelection(backend.models[1], "high", connected=True)
    app = ConvoApp(tmp_path, backend)
    async with app.run_test(size=(80, 24)) as pilot:
        await app.workers.wait_for_complete()
        assert not app.busy
        assert app.selection.model is not None
        assert app.selection.model.id == "model-beta"
        assert app.selection.reasoning_effort == "high"
        assert "Beta" in str(app.query_one("#selection", Static).render())
        assert "thinking high" in str(app.query_one("#thinking", Static).render())
        await pilot.press("shift+tab")
        await app.workers.wait_for_complete()
        assert app.selection.reasoning_effort is None


async def test_explicit_model_refresh_failure_keeps_connected_status_and_composer_usable(tmp_path):
    class OfflineBackend(GenerationBackend):
        async def list_models(self):
            raise RuntimeError("secret-token-and-private-network-details")

    backend = OfflineBackend()
    backend.logged_in = True
    backend.selection = GenerationSelection(connected=True)
    app = ConvoApp(tmp_path, backend)
    async with app.run_test(size=(80, 24)) as pilot:
        await submit(app, pilot, "/models")
        await app.workers.wait_for_complete()
        assert not app.busy
        assert not app.query_one("#prompt", Input).disabled
        assert "choose a model" in str(app.query_one("#selection", Static).render())
        assert "secret-token" not in str(list(app.query(".message"))[-1].render())
        await pilot.press("/")
        assert app.query_one("#command-menu", CommandMenu).display


async def test_startup_never_waits_for_account_network(tmp_path):
    class SlowCatalogBackend(GenerationBackend):
        async def list_models(self):
            raise AssertionError("Startup must not fetch the account catalog")

    backend = SlowCatalogBackend()
    backend.selection = GenerationSelection(backend.models[1], "high", connected=True)
    app = ConvoApp(tmp_path, backend)
    async with app.run_test(size=(80, 24)) as pilot:
        assert not app.busy
        assert not app.query_one("#prompt", Input).disabled
        assert not list(app.workers)
        await pilot.press("/")
        assert app.query_one("#command-menu", CommandMenu).display


async def test_preparation_progress_escape_cancel_failure_and_retry(tmp_path):
    class ProgressBackend(TestBackend):
        def __init__(self):
            super().__init__()
            self.cancelled = False

        async def prepare_with_progress(self, path, progress):
            progress("loading Qwen3… 2s · Esc cancel")
            if path.name == "slow.md":
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            if path.name == "bad.md":
                raise BackendNotConnected("Cannot connect to PostgreSQL. Start Podman.")
            return Document("prepared", path)

    backend = ProgressBackend()
    app = ConvoApp(tmp_path, backend)
    async with app.run_test(size=(80, 24)) as pilot:
        app.file_chosen(tmp_path / "slow.md")
        await pilot.pause()
        status = str(app.query_one("#status", Static).render())
        assert "slow.md" in status and "loading Qwen3" in status
        assert "esc cancel" in str(app.query_one("#keys", Static).render())
        await pilot.press("escape")
        await app.workers.wait_for_complete()
        assert backend.cancelled and not app.busy
        assert app.preparing_path is None
        assert "cancelled" in str(list(app.query(".message"))[-1].render())
        assert app.query_one("#prompt", Input).has_focus
        app.file_chosen(tmp_path / "bad.md")
        await app.workers.wait_for_complete()
        assert "Start Podman" in str(list(app.query(".message"))[-1].render())
        assert not app.query_one("#prompt", Input).disabled
        app.file_chosen(tmp_path / "good.md")
        await app.workers.wait_for_complete()
        assert app.document is not None
        assert app.document.path.name == "good.md"
        assert "ready" in str(app.query_one("#status", Static).render())
        # Cancellation can happen before the Textual worker coroutine starts.
        app.file_chosen(tmp_path / "slow.md")
        await app.action_cancel_or_dismiss()
        assert not app.busy and app.preparing_path is None
        assert app.document.path.name == "good.md"


class PersistentBackend(TestBackend):
    def __init__(self):
        super().__init__()
        self.saved = {}

    async def new_session(self, document=None):
        from uuid import uuid4

        from convo.core.contracts import SessionSnapshot

        snapshot = SessionSnapshot(
            str(uuid4()), document.path.name if document else "New conversation", document
        )
        self.saved[snapshot.id] = snapshot
        return snapshot

    async def list_sessions(self):
        from datetime import UTC, datetime

        from convo.core.contracts import SessionSummary

        return tuple(
            SessionSummary(
                item.id,
                item.title,
                item.document.path.name if item.document else None,
                datetime.now(UTC),
                len(item.history),
            )
            for item in reversed(tuple(self.saved.values()))
        )

    async def load_session(self, session_id):
        return self.saved[session_id]

    async def answer_session(self, session_id, question, progress=None):
        from dataclasses import replace

        from convo.core.contracts import Message

        snapshot = self.saved[session_id]
        if progress:
            progress("reranking candidates…")
        if question == "fail":
            raise BackendNotConnected("Test failure; retry your question.")
        answer = (
            Answer("Hello!")
            if snapshot.document is None
            else await self.answer(snapshot.document, question, snapshot.history)
        )
        self.saved[session_id] = replace(
            snapshot,
            title=question,
            history=snapshot.history
            + (
                Message("user", question),
                Message("assistant", answer.text, answer.sources, answer.structured),
            ),
        )
        return answer


async def test_saved_sessions_picker_new_resume_sources_and_app_restart(tmp_path):
    from convo.ui.sessions import SessionPicker

    backend = PersistentBackend()
    path = tmp_path / "persistent.md"
    path.write_text("A fact")
    app = ConvoApp(tmp_path, backend)
    async with app.run_test(size=(100, 32)) as pilot:
        app.file_chosen(path)
        await app.workers.wait_for_complete()
        first_id = app.session.id
        await submit(app, pilot, "Question one")
        await app.workers.wait_for_complete()
        assert len(backend.saved[first_id].history) == 2
        await submit(app, pilot, "/new")
        await app.workers.wait_for_complete()
        assert app.document is not None
        assert app.session.id != first_id and app.document.path == path
        assert not app.history
        assert len(backend.saved[first_id].history) == 2
        await submit(app, pilot, "/sessions")
        await app.workers.wait_for_complete()
        assert isinstance(app.screen, SessionPicker)
        app.screen.query_one("#session-search", Input).value = "Question one"
        await pilot.pause()
        assert len(app.screen.entries) == 1
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        assert app.session.id == first_id and len(app.history) == 2
        assert app.history[-1].sources
        assert "notes.md · lines" in str(list(app.query(".message"))[-1].render())
        await submit(app, pilot, "fail")
        await app.workers.wait_for_complete()
        assert len(backend.saved[first_id].history) == 2
        assert app.query_one("#prompt", Input).value == "fail"
    # A new UI instance restores from the backend instead of its old Python view.
    restarted = ConvoApp(tmp_path, backend)
    async with restarted.run_test(size=(50, 18)) as pilot:
        await submit(restarted, pilot, f"/sessions {first_id}")
        await restarted.workers.wait_for_complete()
        assert len(restarted.history) == 2
        assert restarted.document.path == path
        await submit(restarted, pilot, "/sessions")
        await restarted.workers.wait_for_complete()
        assert isinstance(restarted.screen, SessionPicker)
        assert restarted.screen.query_one("#session-search", Input).region.bottom <= 18
        restarted.screen.query_one("#session-search", Input).value = "nothing-matches"
        await pilot.pause()
        await pilot.press("enter")
        assert isinstance(restarted.screen, SessionPicker)
        await pilot.press("escape")
        assert restarted.session.id == first_id
        await submit(restarted, pilot, "/reset")
        await restarted.workers.wait_for_complete()
        assert restarted.document is None
        assert backend.saved[first_id].document is not None


async def test_new_session_without_file_and_empty_session_picker(tmp_path):
    from convo.ui.sessions import SessionPicker

    backend = PersistentBackend()
    app = ConvoApp(tmp_path, backend)
    async with app.run_test(size=(80, 24)) as pilot:
        await submit(app, pilot, "/sessions")
        await app.workers.wait_for_complete()
        assert isinstance(app.screen, SessionPicker)
        assert not app.screen.entries
        await pilot.press("enter", "escape")
        await submit(app, pilot, "/new")
        await app.workers.wait_for_complete()
        assert app.session.persisted and app.document is None
        await submit(app, pilot, "hello")
        await app.workers.wait_for_complete()
        assert len(app.history) == 2
        assert app.history[-1].content == "Hello!"
