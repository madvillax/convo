"""The UI/backend boundary. Keep provider and database imports out of this file."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class Document:
    id: str
    path: Path
    indexed: bool = True


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class Source:
    label: str  # e.g. "notes.md · lines 12–24"; never invent a locator.
    excerpt: str


@dataclass(frozen=True)
class Answer:
    text: str
    sources: tuple[Source, ...] = ()


class Backend(Protocol):
    async def prepare(self, path: Path) -> Document:
        """Parse, chunk, embed and index a file; return only when ready."""
        ...

    async def answer(
        self, document: Document, question: str, history: tuple[Message, ...]
    ) -> Answer:
        """Retrieve only this document, call Hermes, return text and real sources.

        history contains completed turns, excluding the current question.
        """
        ...
