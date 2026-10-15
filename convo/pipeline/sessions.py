"""The TUI's active view of a conversation; PostgreSQL is the durable store."""

from dataclasses import dataclass, field
from uuid import uuid4

from convo.core.contracts import Answer, Document, Message, SessionSnapshot


@dataclass
class ChatSession:
    id: str = field(default_factory=lambda: str(uuid4()))
    document: Document | None = None
    history: tuple[Message, ...] = ()
    persisted: bool = False

    def restore(self, snapshot: SessionSnapshot) -> None:
        self.id, self.document, self.history = snapshot.id, snapshot.document, snapshot.history
        self.persisted = True

    def select_document(self, document: Document) -> None:
        self.clear(keep_document=False)
        self.document = document

    def clear(self, *, keep_document: bool = True) -> None:
        self.id = str(uuid4())
        self.history = ()
        self.persisted = False
        if not keep_document:
            self.document = None

    def record_turn(self, question: str, answer: str, result: Answer | None = None) -> None:
        self.history += (
            Message("user", question),
            Message(
                "assistant",
                answer,
                result.sources if result else (),
                result.structured if result else None,
            ),
        )
