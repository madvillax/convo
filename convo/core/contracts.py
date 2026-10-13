"""Shared values and the single boundary between the TUI and backend."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable


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


@dataclass(frozen=True)
class ChunkData:
    text: str
    locator: str


@dataclass(frozen=True)
class Hit:
    text: str
    locator: str
    distance: float


class Backend(Protocol):
    async def prepare(self, path: Path) -> Document:
        """Parse, chunk, embed and index a file; return only when ready."""
        ...

    async def answer(
        self, document: Document, question: str, history: tuple[Message, ...]
    ) -> Answer:
        """Retrieve only this document, call ChatGPT, return text and sources.

        history contains completed turns, excluding the current question.
        """
        ...


@runtime_checkable
class AccountControls(Protocol):
    """Optional ChatGPT sign-in exposed by a completed backend."""

    async def login_openai(self) -> str:
        """Connect a ChatGPT account through Sign in with ChatGPT."""
        ...
