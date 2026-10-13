"""Your orchestration seam. Implement the two methods using backend.md."""

from pathlib import Path

from convo.backend.domain.contracts import Answer, Document, Message


class RagBackend:
    async def prepare(self, path: Path) -> Document:
        """Read → chunk → embed → atomically store the document and chunks."""
        raise NotImplementedError("Implement indexing following backend.md")

    async def answer(
        self, document: Document, question: str, history: tuple[Message, ...]
    ) -> Answer:
        """Embed the question → retrieve this document's chunks → call Hermes."""
        raise NotImplementedError("Implement retrieval and generation following backend.md")
