import asyncio

from textual.widgets import Input, OptionList, Static

from convo.chat.shell import ShellBackend
from convo.core.contracts import Answer, Document, Source
from convo.ui.app import ConvoApp
from convo.ui.files import FilePicker


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
        assert "Connect your backend" in str(list(app.query(".message"))[-1].render())


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
