"""One command registry shared by suggestions, completion, and /help."""

from dataclasses import dataclass

from textual.widgets import OptionList


@dataclass(frozen=True)
class Command:
    name: str
    description: str


COMMANDS = (
    Command("/file", "Choose a file to chat with"),
    Command("/login", "Connect your ChatGPT account"),
    Command("/models", "Choose an account model"),
    Command("/sessions", "Resume a saved conversation"),
    Command("/new", "Start a new chat with this file"),
    Command("/clear", "Start fresh, keep your file"),
    Command("/reset", "Start fresh without a file"),
    Command("/help", "Show commands and keyboard shortcuts"),
    Command("/quit", "Exit Convo"),
)


def matching_commands(text: str) -> tuple[Command, ...]:
    if not text.startswith("/") or any(character.isspace() for character in text):
        return ()
    return tuple(command for command in COMMANDS if command.name.startswith(text.casefold()))


class CommandMenu(OptionList):
    """Let the composer keep focus while arrows and Tab operate suggestions."""

    can_focus = False
