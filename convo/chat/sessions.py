"""Represent the active, process-local chat session for the selected file."""

from dataclasses import dataclass, field
from uuid import uuid4

from convo.chat.history import append_completed_turn
from convo.core.contracts import Document, Message


@dataclass
class ChatSession:
    """One in-memory conversation; it is discarded when Convo exits."""

    id: str = field(default_factory=lambda: str(uuid4()))
    document: Document | None = None
    history: tuple[Message, ...] = ()

    def select_document(self, document: Document) -> None:
        self.id = str(uuid4())
        self.document = document
        self.history = ()

    def clear(self, *, keep_document: bool = True) -> None:
        self.history = ()
        if not keep_document:
            self.document = None
            self.id = str(uuid4())

    def record_turn(self, question: str, answer: str) -> None:
        self.history = append_completed_turn(self.history, question, answer)
