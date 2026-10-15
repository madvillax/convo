"""Own file preparation and document-scoped pgvector search."""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from convo.core.config import Settings
from convo.core.contracts import Document, Hit
from convo.core.exceptions import BackendNotConnected
from convo.db.chunks import replace_chunks, retrieve
from convo.db.documents import upsert_document
from convo.db.session import make_session_factory
from convo.pipeline.chunking import split_documents
from convo.pipeline.embeddings import Embedder
from convo.pipeline.ingestion import MAX_BYTES, read_file
from convo.pipeline.reranking import Reranker
from convo.pipeline.routing import is_overview

_Result = TypeVar("_Result")


class DocumentIndex:
    """Coordinate parsing, embedding, PostgreSQL writes, and scoped retrieval."""

    def __init__(self, settings: Settings) -> None:
        self.engine, self.sessions = make_session_factory(settings)
        self.embedder = Embedder(settings.embedding_model)
        self.reranker = Reranker(settings.reranker_model, settings.rerank_min_score)
        self.candidate_limit = settings.retrieval_candidates
        self.lock = asyncio.Lock()
        self._closed = False
        self.progress: Callable[[str], None] = lambda _stage: None

    def _check_database(self) -> None:
        """Fail before parsing or downloading weights when storage isn't ready."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT id, embedding, search_vector FROM chunks LIMIT 0"))
        except OperationalError as error:
            raise BackendNotConnected(
                "Cannot connect to PostgreSQL. Check DATABASE_URL and start your Podman "
                "machine/container (`podman start convo-postgres`), then select the file again."
            ) from error
        except SQLAlchemyError as error:
            raise BackendNotConnected(
                "The RAG database is not ready. Run `convo --setup`, then select the file again."
            ) from error

    def _prepare(self, path: Path) -> Document:
        self.progress("checking PostgreSQL…")
        self._check_database()
        path = path.resolve(strict=True)
        before = path.stat()
        if before.st_size > MAX_BYTES:
            raise ValueError("File exceeds 10 MB")
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("File grew past the size limit")
        content_hash = hashlib.sha256(raw).hexdigest()

        # The reader parses the exact bytes that are hashed, even if the source changes later.
        self.progress("reading file…")
        with tempfile.TemporaryDirectory(prefix="convo-reader-") as temporary_directory:
            snapshot = Path(temporary_directory) / path.name
            snapshot.write_bytes(raw)
            documents = read_file(snapshot)
        self.progress("loading Qwen3 (first use downloads model weights)…")
        # Loading here gives the UI a distinct stage before tokenization starts.
        self.embedder.model
        self.progress("splitting text…")
        chunks = split_documents(documents, tokenizer=self.embedder.tokenize)
        self.progress(f"embedding {len(chunks)} chunks…")
        vectors = self.embedder.documents([chunk.text for chunk in chunks])

        after = path.stat()
        with path.open("rb") as stream:
            current_raw = stream.read(MAX_BYTES + 1)
        current_hash = hashlib.sha256(current_raw).hexdigest()
        if (
            len(current_raw) > MAX_BYTES
            or current_hash != content_hash
            or (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size)
        ):
            raise ValueError("File changed during indexing; select it again")

        signature = self.embedder.signature
        # Snapshot identity includes path, exact content, and reader/embedding recipe.
        document_id = uuid5(NAMESPACE_URL, f"{path}\n{content_hash}\n{signature}")
        # Complete parsing/model work before opening the transaction; only row writes are atomic.
        self.progress("saving index to PostgreSQL…")
        with self.sessions.begin() as session:
            upsert_document(session, document_id, path, content_hash, signature)
            replace_chunks(session, document_id, chunks, vectors)
        return Document(id=str(document_id), path=path)

    async def prepare(self, path: Path) -> Document:
        self._ensure_open()
        async with self.lock:
            return await self._run_worker(self._prepare, path)

    def _retrieve(self, document: Document, question: str) -> list[Hit]:
        self.progress("embedding the question…")
        vector = self.embedder.query(question)
        overview = is_overview(question)
        self.progress(
            "sampling sections for an overview…" if overview else "searching vectors and keywords…"
        )
        with self.sessions() as session:
            candidates = retrieve(
                session,
                UUID(document.id),
                self.embedder.signature,
                vector,
                question,
                limit=5 if overview else self.candidate_limit,
                overview=overview,
            )
        # The database session is closed before model loading/reranking.
        self.progress("reranking candidates (first use downloads a small model)…")
        return self.reranker.rerank(question, candidates, filter_weak=not overview)

    async def search(self, document: Document, question: str) -> list[Hit]:
        self._ensure_open()
        if not question.strip() or len(question) > 4_000:
            raise ValueError("Use a question between 1 and 4,000 characters")
        async with self.lock:
            return await self._run_worker(self._retrieve, document, question)

    async def _run_worker(self, function: Callable[..., _Result], *args: object) -> _Result:
        """Keep a worker under the lock until its thread has really stopped."""
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Cancelling asyncio.to_thread cannot stop its thread. Wait here so a later
            # operation cannot use the embedder or engine concurrently with that thread.
            try:
                await asyncio.shield(task)
            except Exception:
                pass
            raise

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Document index is closed")

    def close(self) -> None:
        if not self._closed:
            self.engine.dispose()
            self._closed = True
