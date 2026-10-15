"""UI-only adapter. This does not read, embed, upload, or answer from a file."""

from pathlib import Path

from convo.core.contracts import Answer, Document, Message
from convo.core.exceptions import BackendNotConnected


class ShellBackend:
    async def prepare(self, path: Path) -> Document:
        if not path.is_file():
            raise ValueError("That file is no longer available. Use /file to choose another.")
        return Document(id=str(path), path=path, indexed=False)

    async def answer(
        self, document: Document, question: str, history: tuple[Message, ...]
    ) -> Answer:
        raise BackendNotConnected(
            "Shell preview only. Run Convo normally with `uv sync --extra backend` "
            "to connect PostgreSQL, local embeddings, and ChatGPT."
        )
