import asyncio
from pathlib import Path
from typing import ClassVar

from rich.console import Group
from rich.markdown import Markdown
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.events import Resize
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from convo import __version__
from convo.core.contracts import (
    AccountControls,
    Backend,
    Document,
    GenerationControls,
    GenerationSelection,
    Message,
    PreparationControls,
    SessionControls,
)
from convo.core.exceptions import BackendNotConnected
from convo.pipeline.sessions import ChatSession
from convo.ui.commands import COMMANDS, Command, CommandMenu, matching_commands
from convo.ui.files import FilePicker
from convo.ui.models import ModelPicker
from convo.ui.sessions import SessionPicker


class ConvoApp(App[None]):
    TITLE = "convo"
    CSS_PATH = "theme.tcss"
    BINDINGS: ClassVar = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+o", "file", "Choose file"),
        Binding("up", "command_previous", show=False, priority=True),
        Binding("down", "command_next", show=False, priority=True),
        Binding("tab", "complete_command", show=False, priority=True),
        Binding("escape", "cancel_or_dismiss", show=False, priority=True),
        Binding("shift+tab", "cycle_thinking", "Thinking", priority=True),
    ]

    def __init__(self, directory: Path, backend: Backend) -> None:
        super().__init__()
        self.directory = directory.resolve()
        self.backend = backend
        self.session = ChatSession()
        self.busy = False
        self.preparing_path: Path | None = None
        self._cancel_prepare = False
        self.selection = GenerationSelection()
        self.command_choices: tuple[Command, ...] = ()

    @property
    def document(self) -> Document | None:
        return self.session.document

    @property
    def history(self) -> tuple[Message, ...]:
        return self.session.history

    def compose(self) -> ComposeResult:
        yield Static(
            Text.assemble(
                ("convo", "bold white"), (f"  v{__version__} · / for commands", "#777777")
            ),
            id="brand",
        )
        yield Static(str(self.directory), id="directory", markup=False)
        with VerticalScroll(id="conversation"):
            yield Static(
                "Your files. A quiet conversation.\n\nType / to start, or /file to choose a document.",
                id="welcome",
            )
        yield CommandMenu(id="command-menu")
        yield Input(placeholder="Ask about your file, or type / for commands", id="prompt")
        with Horizontal(id="settings"):
            yield Static("", id="selection", markup=False)
            yield Static("", id="thinking", markup=False)
        yield Static("", id="status", markup=False)
        yield Static("enter send · / commands · shift+tab thinking · ctrl+c quit", id="keys")

    def on_mount(self) -> None:
        self.screen.set_class(self.size.width < 70 or self.size.height < 24, "compact")
        if isinstance(self.backend, GenerationControls):
            try:
                self.selection = self.backend.generation_selection()
            except BackendNotConnected:
                pass
        self.update_status()
        self.query_one("#prompt", Input).focus()
        # Restore local preferences immediately. Fetch the account catalog on
        # /models, login, or generation; startup must not wait for the network.

    def on_resize(self, event: Resize) -> None:
        self.screen_stack[0].set_class(event.size.width < 70 or event.size.height < 24, "compact")
        menus = self.query("#command-menu")
        if menus and self.command_choices:
            menus.first(CommandMenu).styles.height = min(
                len(self.command_choices) + 2, 8, max(3, event.size.height - 13)
            )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "cancel_or_dismiss":
            if len(self.screen_stack) != 1:
                return False
            return self.preparing_path is not None or (
                not self.busy and self.query_one("#command-menu", CommandMenu).display
            )
        menu_actions = {"command_previous", "command_next", "complete_command", "dismiss_commands"}
        if action in menu_actions or action == "cycle_thinking":
            if not self.query("#prompt") or len(self.screen_stack) != 1 or self.busy:
                return False
            if not self.query_one("#prompt", Input).has_focus:
                return False
            if action in menu_actions:
                return self.query_one("#command-menu", CommandMenu).display
        return super().check_action(action, parameters)

    def update_status(self, detail: str = "") -> None:
        model = self.selection.model
        label = (
            model.name
            if model
            else "choose a model"
            if self.selection.connected
            else "not connected"
        )
        thinking = self.selection.reasoning_effort or "auto"
        self.query_one("#selection", Static).update(
            Text(f"ChatGPT · {label}", no_wrap=True, overflow="ellipsis")
        )
        self.query_one("#thinking", Static).update(f"thinking {thinking}")
        filename = (
            self.preparing_path.name
            if self.preparing_path
            else self.document.path.name
            if self.document
            else "no file selected"
        )
        state = detail or (
            "ready"
            if self.document and self.document.indexed
            else "shell preview"
            if self.document
            else "choose a file with /file"
        )
        self.query_one("#status", Static).update(
            Text(f"{filename} · {state}", no_wrap=True, overflow="ellipsis")
        )

    def update_command_menu(self, text: str) -> None:
        menu = self.query_one("#command-menu", CommandMenu)
        self.command_choices = matching_commands(text) if not self.busy else ()
        menu.clear_options()
        for command in self.command_choices:
            menu.add_option(
                Option(
                    Text.assemble(
                        (f"{command.name:<9}", "bold #eeeeee"), (command.description, "#888888")
                    ),
                    id=command.name,
                )
            )
        menu.display = bool(self.command_choices)
        if self.command_choices:
            menu.styles.height = min(
                len(self.command_choices) + 2, 8, max(3, self.size.height - 13)
            )
            menu.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "prompt":
            self.update_command_menu(event.value)

    def action_command_previous(self) -> None:
        self.query_one("#command-menu", CommandMenu).action_cursor_up()

    def action_command_next(self) -> None:
        self.query_one("#command-menu", CommandMenu).action_cursor_down()

    def action_complete_command(self) -> None:
        menu = self.query_one("#command-menu", CommandMenu)
        if menu.highlighted is not None and self.command_choices:
            prompt = self.query_one("#prompt", Input)
            prompt.value = self.command_choices[menu.highlighted].name
            prompt.cursor_position = len(prompt.value)

    def action_dismiss_commands(self) -> None:
        self.query_one("#command-menu", CommandMenu).display = False

    async def action_cancel_or_dismiss(self) -> None:
        if self.preparing_path is not None:
            self._cancel_prepare = True
            workers = self.workers.cancel_group(self, "backend")
            await asyncio.gather(*(worker.wait() for worker in workers), return_exceptions=True)
            # A worker cancelled before its coroutine starts cannot execute its
            # finally block. Restore the input in that case as well.
            if self.preparing_path is not None:
                self.preparing_path = None
                self.set_busy(False)
                await self.append_message(
                    "convo", "File preparation cancelled. Choose a file with /file to retry."
                )
        else:
            self.action_dismiss_commands()

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "command-menu" or self.busy:
            return
        event.stop()
        if event.option.id:
            self.query_one("#prompt", Input).value = ""
            self.action_dismiss_commands()
            await self.dispatch_text(event.option.id)

    async def append_message(self, role: str, text: str) -> None:
        welcome = self.query("#welcome")
        if welcome:
            await welcome.first().remove()
        body = (
            Group(Text(role, style="bold #999999"), Markdown(text))
            if role == "chatgpt"
            else Text.assemble((role + "\n", "bold #999999"), (text, "#dddddd"))
        )
        chat = self.query_one("#conversation", VerticalScroll)
        await chat.mount(Static(body, classes="message"))
        chat.scroll_end(animate=False)

    def set_busy(self, busy: bool, detail: str = "") -> None:
        self.busy = busy
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = busy
        self.query_one("#keys", Static).update(
            "esc cancel file preparation · ctrl+c quit"
            if self.preparing_path is not None and busy
            else "enter send · / commands · shift+tab thinking · ctrl+c quit"
        )
        self.update_command_menu(prompt.value)
        self.update_status(detail)
        if not busy and len(self.screen_stack) == 1:
            prompt.focus()

    def action_file(self) -> None:
        if not self.busy and len(self.screen_stack) == 1:
            self.action_dismiss_commands()
            self.push_screen(FilePicker(self.directory), self.file_chosen)

    def file_chosen(self, path: Path | None) -> None:
        if path is not None:
            self.preparing_path = path
            self._cancel_prepare = False
            self.set_busy(True, "starting file worker… · Esc cancel")
            self.prepare_file(path)

    @work(group="backend", exclusive=True)
    async def prepare_file(self, path: Path) -> None:
        try:
            if isinstance(self.backend, PreparationControls):
                document = await self.backend.prepare_with_progress(path, self.update_status)
            else:
                document = await self.backend.prepare(path)
            if isinstance(self.backend, SessionControls):
                snapshot = await self.backend.new_session(document)
                self.session.restore(snapshot)
            else:
                self.session.select_document(document)
            await self.query_one("#conversation", VerticalScroll).remove_children()
            suffix = (
                "Ask a question to begin." if document.indexed else "Shell preview · file selected."
            )
            await self.append_message("file", f"{path.name}\n{suffix}")
        except asyncio.CancelledError:
            if self._cancel_prepare:
                await self.append_message(
                    "convo", "File preparation cancelled. Choose a file with /file to retry."
                )
            raise
        except BackendNotConnected as error:
            await self.append_message("convo", str(error))
        except Exception:
            await self.append_message(
                "error",
                "Could not prepare this file. Check PostgreSQL is running and the file is readable (up to 10 MB).",
            )
        finally:
            self.preparing_path = None
            self.set_busy(False)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt":
            return
        event.stop()
        text = event.value.strip()
        if not text or self.busy:
            return
        menu = self.query_one("#command-menu", CommandMenu)
        if (
            menu.display
            and menu.highlighted is not None
            and self.command_choices
            and matching_commands(event.value) == self.command_choices
        ):
            text = self.command_choices[menu.highlighted].name
        event.input.value = ""
        self.action_dismiss_commands()
        await self.dispatch_text(text)

    async def dispatch_text(self, text: str) -> None:
        if text.startswith("/"):
            parts = text.split()
            command = parts[0].casefold()
            if command == "/file" and len(parts) == 1:
                self.action_file()
            elif command in {"/quit", "/exit"} and len(parts) == 1:
                self.exit()
            elif command in {"/new", "/clear", "/reset"} and len(parts) == 1:
                self.set_busy(True, "starting a new session…")
                self.start_session(keep_document=command != "/reset")
            elif command == "/sessions" and len(parts) <= 2:
                if isinstance(self.backend, SessionControls):
                    self.set_busy(True, "loading saved sessions…")
                    if len(parts) == 2:
                        self.resume_session(parts[1])
                    else:
                        self.show_sessions()
                else:
                    await self.append_message(
                        "convo", "Saved sessions are unavailable in shell preview."
                    )
            elif command == "/login" and len(parts) == 1:
                if isinstance(self.backend, AccountControls):
                    self.set_busy(True, "waiting for ChatGPT sign-in…")
                    self.login_openai()
                else:
                    await self.append_message(
                        "convo",
                        "Account controls are unavailable in shell preview. Launch Convo without --shell.",
                    )
            elif command == "/models" and len(parts) <= 2:
                if isinstance(self.backend, GenerationControls):
                    self.set_busy(True, "loading account models…")
                    if len(parts) == 2:
                        self.change_model(parts[1])
                    else:
                        self.load_models()
                else:
                    await self.append_message(
                        "convo",
                        "Model controls are unavailable in shell preview. Launch Convo without --shell.",
                    )
            elif command == "/help" and len(parts) == 1:
                await self.append_message(
                    "commands",
                    "\n".join(f"{entry.name:<9}{entry.description}" for entry in COMMANDS)
                    + "\n\nCommands: type /, ↑/↓ to move, Tab to complete, Enter to run, Esc to dismiss.\nModels: /models to choose; Shift+Tab cycles thinking.\nCtrl+O chooses a file; Ctrl+C exits.",
                )
            else:
                await self.append_message(
                    "convo", "Unknown command. Type / to see available commands."
                )
        elif self.document is None and not isinstance(self.backend, SessionControls):
            await self.append_message("convo", "Choose a file with /file before asking a question.")
        else:
            await self.append_message("you", text)
            self.set_busy(True, "thinking…")
            self.ask(text)

    @work(group="backend", exclusive=True)
    async def ask(self, question: str) -> None:
        try:
            if isinstance(self.backend, SessionControls):
                if not self.session.persisted:
                    snapshot = await self.backend.new_session(self.document)
                    self.session.restore(snapshot)
                answer = await self.backend.answer_session(
                    self.session.id, question, self.update_status
                )
            else:
                assert self.document is not None
                answer = await self.backend.answer(self.document, question, self.history)
            await self.append_message("chatgpt", answer.text)
            if answer.sources:
                await self.append_message(
                    "sources",
                    "\n\n".join(
                        f"[{index}] {source.label}\n{source.excerpt}"
                        for index, source in enumerate(answer.sources, 1)
                    ),
                )
            self.session.record_turn(question, answer.text, answer)
            if isinstance(self.backend, GenerationControls):
                try:
                    self.selection = self.backend.generation_selection()
                except Exception:
                    self.notify("Answer received. Refresh model settings with /models.")
        except BackendNotConnected as error:
            await self.append_message("convo", str(error))
            self.query_one("#prompt", Input).value = question
        except Exception:
            await self.append_message(
                "error",
                "Could not get an answer. Check your connection or reconnect with /login, then retry.",
            )
            self.query_one("#prompt", Input).value = question
        finally:
            self.set_busy(False)

    @work(group="backend", exclusive=True)
    async def start_session(self, *, keep_document: bool = True) -> None:
        try:
            document = self.document if keep_document else None
            if isinstance(self.backend, SessionControls):
                snapshot = await self.backend.new_session(document)
                self.session.restore(snapshot)
            else:
                self.session.clear(keep_document=keep_document)
            self.query_one("#prompt", Input).value = ""
            await self.query_one("#conversation", VerticalScroll).remove_children()
            await self.append_message(
                "convo",
                f"New conversation · {document.path.name}"
                if document
                else "New conversation. Choose a file with /file to begin.",
            )
        except BackendNotConnected as error:
            await self.append_message("convo", str(error))
        except Exception:
            await self.append_message(
                "error", "Could not create a session. Check PostgreSQL and retry /new."
            )
        finally:
            self.set_busy(False)

    @work(group="backend", exclusive=True)
    async def show_sessions(self) -> None:
        assert isinstance(self.backend, SessionControls)
        sessions = None
        try:
            sessions = await self.backend.list_sessions()
        except BackendNotConnected as error:
            await self.append_message("convo", str(error))
        except Exception:
            await self.append_message(
                "error", "Could not load saved conversations. Retry /sessions."
            )
        finally:
            self.set_busy(False)
        if sessions is not None:
            self.push_screen(SessionPicker(sessions, self.session.id), self.session_chosen)

    def session_chosen(self, session_id: str | None) -> None:
        if session_id is not None:
            self.set_busy(True, "restoring conversation…")
            self.resume_session(session_id)

    @work(group="backend", exclusive=True)
    async def resume_session(self, session_id: str) -> None:
        assert isinstance(self.backend, SessionControls)
        try:
            snapshot = await self.backend.load_session(session_id)
            self.session.restore(snapshot)
            self.query_one("#prompt", Input).value = ""
            await self.query_one("#conversation", VerticalScroll).remove_children()
            await self.append_message("convo", f"Resumed: {snapshot.title}")
            for message in snapshot.history:
                await self.append_message(
                    "you" if message.role == "user" else "chatgpt", message.content
                )
                if message.sources:
                    await self.append_message(
                        "sources",
                        "\n\n".join(
                            f"[{index}] {source.label}\n{source.excerpt}"
                            for index, source in enumerate(message.sources, 1)
                        ),
                    )
        except BackendNotConnected as error:
            await self.append_message("convo", str(error))
        except Exception:
            await self.append_message(
                "error", "Could not restore this conversation. Retry /sessions."
            )
        finally:
            self.set_busy(False)

    @work(group="backend", exclusive=True)
    async def login_openai(self) -> None:
        assert isinstance(self.backend, AccountControls)
        try:
            account = await self.backend.login_openai()
            await self.append_message(
                "convo",
                f"Connected ChatGPT account: {account}\nUse /models to choose a model; Shift+Tab changes thinking.",
            )
            if isinstance(self.backend, GenerationControls):
                try:
                    self.selection = self.backend.generation_selection()
                    await self.backend.list_models()
                    self.selection = self.backend.generation_selection()
                except Exception:
                    await self.append_message(
                        "convo",
                        "Account connected, but models could not be loaded. Use /models to retry.",
                    )
        except BackendNotConnected as error:
            await self.append_message("convo", str(error))
        except Exception:
            await self.append_message(
                "error", "ChatGPT sign-in failed. Check your connection and retry /login."
            )
        finally:
            self.set_busy(False)

    @work(group="backend", exclusive=True)
    async def load_models(self, *, show_picker: bool = True) -> None:
        assert isinstance(self.backend, GenerationControls)
        models = ()
        try:
            models = await self.backend.list_models()
            self.selection = self.backend.generation_selection()
            if not models:
                await self.append_message(
                    "convo", "No models are available to this account. Reconnect with /login."
                )
        except BackendNotConnected as error:
            models = ()
            await self.append_message("convo", str(error))
        except Exception:
            models = ()
            await self.append_message(
                "error", "Could not load ChatGPT models. Check your connection and retry /models."
            )
        finally:
            self.set_busy(False)
        if show_picker and models:
            selected = self.selection.model.id if self.selection.model else None
            self.push_screen(ModelPicker(models, selected), self.model_chosen)

    def model_chosen(self, model_id: str | None) -> None:
        if model_id is not None:
            self.set_busy(True, "changing model…")
            self.change_model(model_id)

    @work(group="backend", exclusive=True)
    async def change_model(self, model_id: str) -> None:
        assert isinstance(self.backend, GenerationControls)
        try:
            self.selection = await self.backend.select_model(model_id)
        except (BackendNotConnected, ValueError) as error:
            await self.append_message("convo", str(error))
        except Exception:
            await self.append_message("error", "Could not change the model. Retry /models.")
        finally:
            self.set_busy(False)

    def action_cycle_thinking(self) -> None:
        if not isinstance(self.backend, GenerationControls):
            self.notify("Thinking controls are unavailable in shell preview.")
            return
        self.set_busy(True, "updating thinking…")
        self.cycle_thinking()

    @work(group="backend", exclusive=True)
    async def cycle_thinking(self) -> None:
        assert isinstance(self.backend, GenerationControls)
        try:
            self.selection = await self.backend.cycle_reasoning()
            if self.selection.model and not self.selection.model.reasoning_efforts:
                self.notify("This model uses automatic thinking; no adjustable levels are known.")
        except BackendNotConnected as error:
            await self.append_message("convo", str(error))
        except Exception:
            await self.append_message(
                "error", "Could not change thinking. Refresh the account models with /models."
            )
        finally:
            self.set_busy(False)
