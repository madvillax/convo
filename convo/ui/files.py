"""A searchable picker rooted at the directory where Convo was launched."""

from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

SUPPORTED = {".txt", ".md", ".pdf", ".docx", ".csv", ".json", ".py", ".rst", ".log"}


class FilePicker(ModalScreen[Path | None]):
    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root.resolve()
        self.folder = self.root
        self.entries: list[Path] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Static("Choose a file", id="picker-title")
            yield Static("", id="picker-path", markup=False)
            yield Input(placeholder="Filter files…", id="file-search")
            yield OptionList(id="file-options")
            yield Static("↑ ↓ move   enter select   tab list   esc close", id="picker-help")

    def on_mount(self) -> None:
        self.refresh_entries()
        self.query_one("#file-search", Input).focus()

    def refresh_entries(self, search: str = "") -> None:
        options = self.query_one("#file-options", OptionList)
        options.clear_options()
        self.entries = []
        self.query_one("#picker-path", Static).update(str(self.folder))
        try:
            candidates = []
            for path in self.folder.iterdir():
                if path.name.startswith(".") or path.is_symlink():
                    continue
                if (
                    path.is_dir() or path.suffix.lower() in SUPPORTED
                ) and search.casefold() in path.name.casefold():
                    candidates.append(path)
            self.entries = sorted(candidates, key=lambda p: (not p.is_dir(), p.name.casefold()))
            if self.folder != self.root:
                self.entries.insert(0, self.folder.parent)
            for index, path in enumerate(self.entries):
                name = (
                    "../"
                    if path == self.folder.parent
                    else path.name + ("/" if path.is_dir() else "")
                )
                options.add_option(Option(Text(name), id=str(index)))
            if not self.entries:
                options.add_option(Option("No supported files found", disabled=True))
            else:
                options.highlighted = 0
        except OSError:
            options.add_option(Option("Cannot read this directory", disabled=True))

    def on_input_changed(self, event: Input.Changed) -> None:
        self.refresh_entries(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        options = self.query_one("#file-options", OptionList)
        if options.highlighted is not None and self.entries:
            self.choose(options.highlighted)

    def on_key(self, event) -> None:
        if self.query_one("#file-search", Input).has_focus and event.key in {"down", "up"}:
            options = self.query_one("#file-options", OptionList)
            options.focus()
            event.stop()
            event.prevent_default()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.choose(event.option_index)

    def choose(self, index: int) -> None:
        path = self.entries[index].resolve()
        if not path.is_relative_to(self.root):
            return
        if path.is_dir():
            self.folder = path
            self.query_one("#file-search", Input).value = ""
            self.refresh_entries()
            self.query_one("#file-search", Input).focus()
        elif path.is_file():
            self.dismiss(path)
        else:
            self.refresh_entries()

    def action_cancel(self) -> None:
        self.dismiss(None)
