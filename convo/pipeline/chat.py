"""One chat flow: route, retrieve/rerank, generate a validated answer, persist the turn."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from convo.core.config import Settings
from convo.core.contracts import (
    Answer,
    ChatModel,
    Document,
    GenerationSelection,
    Message,
    SessionSnapshot,
    SessionSummary,
)
from convo.llm.auth import ChatGPTAuth
from convo.llm.client import ChatGPTProvider
from convo.llm.credentials import KeyringCredentialStore
from convo.pipeline.routing import conversation_reply, search_query
from convo.pipeline.worker import IndexWorker

if TYPE_CHECKING:
    from convo.db.conversations import Conversations


class RagBackend:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.documents = IndexWorker(settings)
        self.auth = ChatGPTAuth(KeyringCredentialStore())
        self.chat = ChatGPTProvider(self.auth)
        self._conversations: Conversations | None = None
        self._session_lock = asyncio.Lock()

    def _store(self) -> Conversations:
        if self._conversations is None:
            from convo.db.conversations import Conversations

            self._conversations = Conversations(self.settings)
        return self._conversations

    async def prepare(self, path: Path) -> Document:
        return await self.documents.prepare(path)

    async def prepare_with_progress(self, path: Path, progress: Callable[[str], None]) -> Document:
        return await self.documents.prepare(path, progress)

    async def _answer(
        self,
        document: Document | None,
        question: str,
        history: tuple[Message, ...],
        progress: Callable[[str], None] | None = None,
    ) -> Answer:
        if not question.strip() or len(question) > 4_000:
            from convo.core.exceptions import BackendNotConnected

            raise BackendNotConnected("Use a question between 1 and 4,000 characters.")
        conversational = conversation_reply(question)
        if conversational:
            return Answer(conversational)
        if document is None:
            return Answer("Choose a file with /file, then ask me a question about it.")
        query = search_query(question, history)
        hits = await self.documents.search(document, query, progress)
        if progress:
            progress("writing a grounded answer…")
        return await self.chat.answer(document.path.name, question, history, hits)

    async def answer(
        self, document: Document, question: str, history: tuple[Message, ...]
    ) -> Answer:
        return await self._answer(document, question, history)

    async def new_session(self, document: Document | None = None) -> SessionSnapshot:
        async with self._session_lock:
            return await asyncio.to_thread(lambda: self._store().create(document))

    async def list_sessions(self) -> tuple[SessionSummary, ...]:
        async with self._session_lock:
            return await asyncio.to_thread(lambda: self._store().list())

    async def load_session(self, session_id: str) -> SessionSnapshot:
        async with self._session_lock:
            return await asyncio.to_thread(lambda: self._store().load(session_id))

    async def answer_session(
        self, session_id: str, question: str, progress: Callable[[str], None] | None = None
    ) -> Answer:
        # No database transaction stays open during embedding or the LLM request.
        snapshot = await self.load_session(session_id)
        answer = await self._answer(snapshot.document, question, snapshot.history, progress)
        async with self._session_lock:
            await asyncio.to_thread(
                lambda: self._store().append_turn(
                    session_id, question, answer, expected_messages=len(snapshot.history)
                )
            )
        return answer

    async def login_openai(self) -> str:
        account = await self.auth.login()
        self.chat.reset_catalog()
        return account

    def generation_selection(self) -> GenerationSelection:
        return self.chat.generation_selection()

    async def list_models(self) -> tuple[ChatModel, ...]:
        return await self.chat.list_models()

    async def select_model(self, model_id: str) -> GenerationSelection:
        return await self.chat.select_model(model_id)

    async def cycle_reasoning(self) -> GenerationSelection:
        return await self.chat.cycle_reasoning()

    def close(self) -> None:
        self.documents.close()
        if self._conversations is not None:
            self._conversations.close()
