"""Direct thinking selection and the configurable cycling shortcut."""

import re
from typing import ClassVar

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from convo.core.contracts import ChatModel, ReasoningEffort

GOLD = "#e6b85c"


def thinking_key(value: str) -> str:
    """Accept terminal-friendly shortcuts without replacing essential controls."""
    key = value.strip().lower()
    if key == "shift+tab" or re.fullmatch(r"f(?:[3-9]|1[0-9]|2[0-4])", key):
        return key
    if re.fullmatch(r"(?:ctrl|alt)\+[a-z]", key) and key not in {
        "ctrl+c",
        "ctrl+o",
        "ctrl+i",
        "ctrl+j",
        "ctrl+m",
        "ctrl+h",
        "ctrl+z",
    }:
        return key
    raise ValueError(
        "Use ctrl+t, another Ctrl/Alt letter, or F3–F24; reserved keys are unavailable."
    )


class ThinkingPicker(ModalScreen[str | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def __init__(self, model: ChatModel, selected: ReasoningEffort | None) -> None:
        super().__init__()
        self.model = model
        self.selected = selected or "auto"

    def compose(self) -> ComposeResult:
        with Vertical(id="thinking-picker"):
            yield Static("Thinking effort", id="thinking-title")
            yield Static(self.model.name, id="thinking-subtitle", markup=False)
            options = [Option("auto  ·  model default", id="auto")]
            options.extend(Option(effort, id=effort) for effort in self.model.reasoning_efforts)
            yield OptionList(*options, id="thinking-options")
            yield Static("↑ ↓ move   enter select   esc cancel", id="thinking-help")

    def on_mount(self) -> None:
        self.set_class(self.app.size.height < 24, "compact")
        options = self.query_one("#thinking-options", OptionList)
        choices = ("auto", *self.model.reasoning_efforts)
        options.highlighted = choices.index(self.selected) if self.selected in choices else 0
        options.focus()

    def on_resize(self, event: Resize) -> None:
        self.set_class(event.size.height < 24, "compact")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        self.dismiss(None)
