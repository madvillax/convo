"""UI-only adapter. This does not read, embed, upload, or answer from a file."""

from pathlib import Path

from convo.backend.domain.contracts import Answer, Document, Message
from convo.backend.domain.errors import BackendNotConnected


class ShellBackend:
    async def prepare(self, path: Path) -> Document:
        if not path.is_file():
            raise ValueError("That file is no longer available. Use /file to choose another.")
        return Document(id=str(path), path=path, indexed=False)

    async def answer(
        self, document: Document, question: str, history: tuple[Message, ...]
    ) -> Answer:
        raise BackendNotConnected(
            "File selected. Connect your backend using backend.md to get Hermes answers."
        )
