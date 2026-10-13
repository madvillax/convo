from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from convo import __version__
from convo.chat.sessions import ChatSession
from convo.core.contracts import (
    AccountControls,
    Backend,
    Document,
    Message,
)
from convo.core.exceptions import BackendNotConnected
from convo.ui.files import FilePicker


class ConvoApp(App[None]):
    TITLE = "convo"
    CSS_PATH = "theme.tcss"
    BINDINGS: ClassVar = [("ctrl+c", "quit", "Quit"), ("ctrl+o", "file", "Choose file")]

    def __init__(self, directory: Path, backend: Backend) -> None:
        super().__init__()
        self.directory = directory.resolve()
        self.backend = backend
        self.session = ChatSession()
        self.busy = False

    @property
    def document(self) -> Document | None:
        return self.session.document

    @property
    def history(self) -> tuple[Message, ...]:
        return self.session.history

    def compose(self) -> ComposeResult:
        yield Static(
            Text.assemble(
                ("convo", "bold white"), (f"  v{__version__} · /help for commands", "#777777")
            ),
            id="brand",
        )
        yield Static(str(self.directory), id="directory", markup=False)
        with VerticalScroll(id="conversation"):
            yield Static(
                "Your files. A quiet conversation.\n\nType /file to choose a document.",
                id="welcome",
            )
        yield Input(placeholder="Ask about your file, or type /file", id="prompt")
        yield Static("", id="status", markup=False)
        yield Static("enter send   ·   ctrl+o files   ·   ctrl+c quit", id="keys")

    def on_mount(self) -> None:
        self.update_status()
        self.query_one("#prompt", Input).focus()

    def update_status(self, detail: str = "") -> None:
        file = self.document.path.name if self.document else "no file selected"
        state = detail or (
            "ready" if self.document and self.document.indexed else "backend pending"
        )
        self.query_one("#status", Static).update(f"ChatGPT · qwen3 embeddings · {file} · {state}")

    async def append_message(self, role: str, text: str) -> None:
        welcome = self.query("#welcome")
        if welcome:
            await welcome.first().remove()
        body = Text.assemble((role + "\n", "bold #999999"), (text, "#dddddd"))
        chat = self.query_one("#conversation", VerticalScroll)
        await chat.mount(Static(body, classes="message"))
        chat.scroll_end(animate=False)

    def set_busy(self, busy: bool, detail: str = "") -> None:
        self.busy = busy
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = busy
        self.update_status(detail)
        if not busy:
            prompt.focus()

    def action_file(self) -> None:
        if not self.busy and not isinstance(self.screen, FilePicker):
            self.push_screen(FilePicker(self.directory), self.file_chosen)

    def file_chosen(self, path: Path | None) -> None:
        if path is not None:
            self.set_busy(True, "preparing file…")
            self.prepare_file(path)

    @work(group="backend", exclusive=True)
    async def prepare_file(self, path: Path) -> None:
        try:
            document = await self.backend.prepare(path)
            self.session.select_document(document)
            await self.query_one("#conversation", VerticalScroll).remove_children()
            suffix = (
                "Ask a question to begin."
                if document.indexed
                else "Backend pending — follow backend.md to connect a model provider."
            )
            await self.append_message("file", f"{path.name}\n{suffix}")
        except Exception:  # noqa: BLE001 - isolate errors from the user-supplied backend
            await self.append_message(
                "error", "Could not prepare this file. Check your backend and try /file again."
            )
        finally:
            self.set_busy(False)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text or self.busy:
            return
        event.input.value = ""
        if text.startswith("/"):
            command = text.lower().split()
            if command == ["/file"]:
                self.action_file()
            elif command in (["/quit"], ["/exit"]):
                self.exit()
            elif command in (["/clear"], ["/reset"]):
                self.session.clear(keep_document=command != ["/reset"])
                await self.query_one("#conversation", VerticalScroll).remove_children()
                await self.append_message(
                    "convo",
                    "Conversation cleared."
                    if self.document
                    else "Type /file to choose a document.",
                )
                self.update_status()
            elif command == ["/login"]:
                if isinstance(self.backend, AccountControls):
                    self.set_busy(True, "waiting for ChatGPT sign-in…")
                    self.login_openai()
                else:
                    await self.append_message(
                        "convo",
                        "ChatGPT sign-in is not wired yet. Follow backend.md to add /login.",
                    )
            elif command == ["/help"]:
                await self.append_message(
                    "commands",
                    "/file   choose a file\n/login  connect your ChatGPT account\n/clear  clear conversation, keep file\n/reset  clear conversation and file\n/quit   exit\n\nPicker: type to filter, ↑/↓ to move, Enter to select, Esc to close.",
                )
            else:
                await self.append_message("convo", "Unknown command. Type /help for commands.")
        elif self.document is None:
            await self.append_message("convo", "Choose a file with /file before asking a question.")
        else:
            await self.append_message("you", text)
            self.set_busy(True, "thinking…")
            self.ask(text)

    @work(group="backend", exclusive=True)
    async def ask(self, question: str) -> None:
        try:
            assert self.document is not None
            answer = await self.backend.answer(self.document, question, self.history)
            await self.append_message("chatgpt", answer.text)
            if answer.sources:
                await self.append_message(
                    "sources",
                    "\n\n".join(
                        f"[{i}] {source.label}\n{source.excerpt}"
                        for i, source in enumerate(answer.sources, 1)
                    ),
                )
            self.session.record_turn(question, answer.text)
        except BackendNotConnected as error:
            await self.append_message("convo", str(error))
        except Exception:  # noqa: BLE001 - isolate errors from the user-supplied backend
            # Avoid rendering raw provider errors which may include credentials.
            await self.append_message(
                "error", "Could not get an answer. Check your backend configuration and try again."
            )
        finally:
            self.set_busy(False)

    @work(group="backend", exclusive=True)
    async def login_openai(self) -> None:
        assert isinstance(self.backend, AccountControls)
        try:
            account = await self.backend.login_openai()
            await self.append_message("convo", f"Connected ChatGPT account: {account}")
        except BackendNotConnected as error:
            await self.append_message("convo", str(error))
        except Exception:  # noqa: BLE001 - never render tokens or raw provider errors
            await self.append_message(
                "error", "ChatGPT sign-in failed. Check the backend log and retry /login."
            )
        finally:
            self.set_busy(False)
