"""A searchable picker populated only from the signed-in account's catalog."""

from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from convo.core.contracts import ChatModel


class ModelPicker(ModalScreen[str | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def __init__(self, models: tuple[ChatModel, ...], selected: str | None) -> None:
        super().__init__()
        self.models = models
        self.selected = selected
        self.entries: tuple[ChatModel, ...] = ()

    def compose(self) -> ComposeResult:
        with Vertical(id="model-picker"):
            yield Static("Choose a ChatGPT model", id="model-title")
            yield Static("Available to your connected account", id="model-subtitle")
            yield Input(placeholder="Filter by model name…", id="model-search")
            yield OptionList(id="model-options")
            yield Static("↑ ↓ move   enter select   esc cancel", id="model-help")

    def on_mount(self) -> None:
        self.refresh_entries()
        self.query_one("#model-search", Input).focus()

    def refresh_entries(self, search: str = "") -> None:
        options = self.query_one("#model-options", OptionList)
        options.clear_options()
        self.entries = tuple(
            model
            for model in self.models
            if search.casefold() in f"{model.name} {model.id}".casefold()
        )
        for model in self.entries:
            label = Text()
            label.append("● " if model.id == self.selected else "  ", style="#aaaaaa")
            label.append(model.name, style="bold")
            label.append(f"\n  {model.id}", style="#888888")
            options.add_option(Option(label, id=model.id))
        if not self.entries:
            options.add_option(Option("No matching models", disabled=True))
        else:
            options.highlighted = next(
                (index for index, model in enumerate(self.entries) if model.id == self.selected), 0
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.refresh_entries(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        highlighted = self.query_one("#model-options", OptionList).highlighted
        if highlighted is not None and self.entries:
            self.dismiss(self.entries[highlighted].id)

    def on_key(self, event: Key) -> None:
        if self.query_one("#model-search", Input).has_focus and event.key in {"up", "down"}:
            options = self.query_one("#model-options", OptionList)
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
