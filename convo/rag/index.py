"""Own file preparation and document-scoped search.

DocumentIndex hides parsing, embedding, and database work from the chat workflow.
Implement the reference class in backend.md step 9.1.
"""

from pathlib import Path

from convo.core.config import Settings
from convo.core.contracts import Document, Hit


class DocumentIndex:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def prepare(self, path: Path) -> Document:
        """Read, split, embed, and commit the selected file snapshot."""
        raise NotImplementedError("Implement DocumentIndex.prepare() from backend.md")

    async def search(self, document: Document, question: str) -> list[Hit]:
        """Return relevant excerpts only from this document snapshot."""
        raise NotImplementedError("Implement DocumentIndex.search() from backend.md")

    def close(self) -> None:
        """Dispose resources owned by this document index."""
        raise NotImplementedError("Implement engine disposal following backend.md")
