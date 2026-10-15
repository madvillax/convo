"""SQLAlchemy storage for sessions and atomic, completed conversation turns."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from convo.core.config import Settings
from convo.core.contracts import (
    Answer,
    Document,
    Message,
    SessionSnapshot,
    SessionSummary,
    Source,
)
from convo.core.exceptions import BackendNotConnected
from convo.db.models import ChatSessionRow, DocumentRow, MessageRow
from convo.db.session import make_session_factory

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

    from convo.db.session import SessionFactory


class Conversations:
    """Created cheaply at startup; connect only when a session is requested."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine: Engine | None = None
        self.sessions: SessionFactory | None = None

    @contextmanager
    def transaction(self) -> Generator[Session]:
        try:
            if self.sessions is None:
                self.engine, self.sessions = make_session_factory(self.settings)
            with self.sessions.begin() as session:
                yield session
        except SQLAlchemyError as error:
            raise BackendNotConnected(
                "Could not access saved conversations. Check PostgreSQL/Podman and run "
                "`uv run --extra backend alembic upgrade head` from the project directory."
            ) from error

    def create(self, document: Document | None = None) -> SessionSnapshot:
        session_id = uuid4()
        title = document.path.name[:200] if document else "New conversation"
        with self.transaction() as session:
            if document and session.get(DocumentRow, UUID(document.id)) is None:
                raise BackendNotConnected("The document snapshot is missing. Select it with /file.")
            session.add(
                ChatSessionRow(
                    id=session_id,
                    document_id=UUID(document.id) if document else None,
                    title=title,
                )
            )
        return SessionSnapshot(str(session_id), title, document)

    def list(self) -> tuple[SessionSummary, ...]:
        with self.transaction() as session:
            statement = (
                select(ChatSessionRow, DocumentRow.source_path, func.count(MessageRow.id))
                .outerjoin(DocumentRow, DocumentRow.id == ChatSessionRow.document_id)
                .outerjoin(MessageRow, MessageRow.session_id == ChatSessionRow.id)
                .group_by(ChatSessionRow.id, DocumentRow.source_path)
                .order_by(ChatSessionRow.updated_at.desc(), ChatSessionRow.id)
            )
            return tuple(
                SessionSummary(
                    str(row.id), row.title, Path(path).name if path else None, row.updated_at, count
                )
                for row, path, count in session.execute(statement)
            )

    def load(self, session_id: str) -> SessionSnapshot:
        try:
            identity = UUID(session_id)
        except ValueError as error:
            raise BackendNotConnected("Choose a valid session with /sessions.") from error
        with self.transaction() as session:
            row = session.get(ChatSessionRow, identity)
            if row is None:
                raise BackendNotConnected("This conversation no longer exists. Use /sessions.")
            document = None
            if row.document_id:
                stored = session.get(DocumentRow, row.document_id)
                if stored is None:
                    raise BackendNotConnected("The saved document snapshot is missing.")
                document = Document(str(stored.id), Path(stored.source_path))
            messages = session.scalars(
                select(MessageRow)
                .where(MessageRow.session_id == identity)
                .order_by(MessageRow.ordinal)
            ).all()
            history = tuple(
                Message(
                    cast(Literal["user", "assistant"], message.role),
                    message.content,
                    tuple(Source(**source) for source in message.sources),
                    message.structured,
                )
                for message in messages
            )
            return SessionSnapshot(str(row.id), row.title, document, history)

    def append_turn(
        self, session_id: str, question: str, answer: Answer, expected_messages: int
    ) -> None:
        """Commit both messages together; never save an incomplete or stale answer."""
        identity = UUID(session_id)
        with self.transaction() as session:
            row = session.get(ChatSessionRow, identity, with_for_update=True)
            if row is None:
                raise BackendNotConnected("The conversation no longer exists. Use /sessions.")
            count = (
                session.scalar(
                    select(func.count())
                    .select_from(MessageRow)
                    .where(MessageRow.session_id == identity)
                )
                or 0
            )
            if count != expected_messages:
                raise BackendNotConnected(
                    "This conversation changed in another process. Reopen it with /sessions and retry."
                )
            session.add_all(
                [
                    MessageRow(
                        session_id=identity,
                        ordinal=count,
                        role="user",
                        content=question,
                        sources=[],
                        structured=None,
                    ),
                    MessageRow(
                        session_id=identity,
                        ordinal=count + 1,
                        role="assistant",
                        content=answer.text,
                        sources=[asdict(source) for source in answer.sources],
                        structured=answer.structured,
                    ),
                ]
            )
            if count == 0:
                row.title = question.strip()[:200]
            row.updated_at = datetime.now(UTC)

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
            self.engine, self.sessions = None, None
