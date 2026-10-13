"""Expose the backend API to the TUI and coordinate documents with chat."""

from pathlib import Path

from convo.auth.chatgpt import ChatGPTAuth
from convo.auth.credentials import KeyringCredentialStore
from convo.core.config import Settings
from convo.core.contracts import Answer, Document, Message
from convo.providers.base import ChatProvider
from convo.providers.openai import ChatGPTProvider
from convo.rag.index import DocumentIndex


class RagBackend:
    def __init__(self, settings: Settings):
        self.documents = DocumentIndex(settings)
        self.auth = ChatGPTAuth(KeyringCredentialStore())
        self.chat: ChatProvider = ChatGPTProvider(self.auth)

    async def prepare(self, path: Path) -> Document:
        """Delegate file preparation to DocumentIndex."""
        raise NotImplementedError("Implement indexing following backend.md")

    async def answer(
        self, document: Document, question: str, history: tuple[Message, ...]
    ) -> Answer:
        """Search through DocumentIndex, then ask the ChatGPT client."""
        raise NotImplementedError("Implement retrieval and generation following backend.md")

    async def login_openai(self) -> str:
        """Connect a ChatGPT account for the TUI's /login command."""
        raise NotImplementedError("Implement SIWC login following backend.md step 8")

    def close(self) -> None:
        """Release resources through DocumentIndex.close()."""
        raise NotImplementedError("Implement cleanup following backend.md step 9")
