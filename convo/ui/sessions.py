"""Search and resume the conversations stored in PostgreSQL."""

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from convo.core.contracts import SessionSummary


class SessionPicker(ModalScreen[str | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def __init__(self, sessions: tuple[SessionSummary, ...], selected: str | None) -> None:
        super().__init__()
        self.sessions, self.selected = sessions, selected
        self.entries: tuple[SessionSummary, ...] = ()

    def compose(self) -> ComposeResult:
        with Vertical(id="session-picker"):
            yield Static("Your conversations", id="session-title")
            yield Static("Resume a saved file and its history", id="session-subtitle")
            yield Input(placeholder="Filter by title, file, or session ID…", id="session-search")
            yield OptionList(id="session-options")
            yield Static("↑ ↓ move   enter resume   esc cancel", id="session-help")

    def on_mount(self) -> None:
        self.refresh_entries()
        self.query_one("#session-search", Input).focus()

    def refresh_entries(self, search: str = "") -> None:
        options = self.query_one("#session-options", OptionList)
        options.clear_options()
        self.entries = tuple(
            session
            for session in self.sessions
            if search.casefold()
            in f"{session.title} {session.filename or ''} {session.id}".casefold()
        )
        for session in self.entries:
            label = Text()
            label.append("● " if session.id == self.selected else "  ", style="#aaaaaa")
            label.append(session.title.replace("\n", " ")[:100], style="bold")
            date = session.updated_at.astimezone().strftime("%d %b %H:%M")
            turns = session.message_count // 2
            turn_label = "turn" if turns == 1 else "turns"
            label.append(
                f"\n  {session.filename or 'no file'} · {turns} {turn_label} · {date}",
                style="#888888",
            )
            options.add_option(Option(label, id=session.id))
        if not self.entries:
            options.add_option(
                Option(
                    "No matching sessions"
                    if self.sessions
                    else "No saved sessions yet. Start with /new or /file.",
                    disabled=True,
                )
            )
        else:
            options.highlighted = next(
                (index for index, item in enumerate(self.entries) if item.id == self.selected), 0
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.refresh_entries(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        highlighted = self.query_one("#session-options", OptionList).highlighted
        if highlighted is not None and self.entries:
            self.dismiss(self.entries[highlighted].id)

    def on_key(self, event: Key) -> None:
        if self.query_one("#session-search", Input).has_focus and event.key in {"up", "down"}:
            options = self.query_one("#session-options", OptionList)
            if event.key == "down":
                options.action_cursor_down()
            else:
                options.action_cursor_up()
            event.stop()
            event.prevent_default()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if 0 <= event.option_index < len(self.entries):
            self.dismiss(self.entries[event.option_index].id)

    def action_cancel(self) -> None:
        self.dismiss(None)
