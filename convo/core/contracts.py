"""Shared values and the single boundary between the TUI and backend."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)


@dataclass(frozen=True)
class ChatModel:
    """A displayable model from the connected account's catalog."""

    id: str
    name: str
    reasoning_efforts: tuple[ReasoningEffort, ...] = ()
    default_reasoning_effort: ReasoningEffort | None = None


@dataclass(frozen=True)
class GenerationSelection:
    model: ChatModel | None = None
    reasoning_effort: ReasoningEffort | None = None  # None lets the server choose its default.
    connected: bool = False


@dataclass(frozen=True)
class Document:
    id: str
    path: Path
    indexed: bool = True


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str
    sources: tuple[Source, ...] = ()
    structured: dict[str, object] | None = None


@dataclass(frozen=True)
class Source:
    label: str  # e.g. "notes.md · lines 12–24"; never invent a locator.
    excerpt: str


@dataclass(frozen=True)
class Answer:
    text: str
    sources: tuple[Source, ...] = ()
    structured: dict[str, object] | None = None


@dataclass(frozen=True)
class ChunkData:
    text: str
    locator: str


@dataclass(frozen=True)
class Hit:
    text: str
    locator: str
    distance: float
    chunk_id: int | None = None
    score: float | None = None


@dataclass(frozen=True)
class SessionSummary:
    id: str
    title: str
    filename: str | None
    updated_at: datetime
    message_count: int


@dataclass(frozen=True)
class SessionSnapshot:
    id: str
    title: str
    document: Document | None
    history: tuple[Message, ...] = ()


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
class PreparationControls(Protocol):
    """Optional progress reporting; callbacks run on the UI event loop."""

    async def prepare_with_progress(
        self, path: Path, progress: Callable[[str], None]
    ) -> Document: ...


@runtime_checkable
class SessionControls(Protocol):
    """Durable sessions; successful turns are saved before the response returns."""

    async def new_session(self, document: Document | None = None) -> SessionSnapshot: ...

    async def list_sessions(self) -> tuple[SessionSummary, ...]: ...

    async def load_session(self, session_id: str) -> SessionSnapshot: ...

    async def answer_session(
        self, session_id: str, question: str, progress: Callable[[str], None] | None = None
    ) -> Answer: ...


@runtime_checkable
class AccountControls(Protocol):
    """Optional ChatGPT sign-in exposed by a completed backend."""

    async def login_openai(self) -> str:
        """Connect a ChatGPT account through Sign in with ChatGPT."""
        ...


@runtime_checkable
class GenerationControls(Protocol):
    """Optional account model and thinking controls, independent of the TUI."""

    def generation_selection(self) -> GenerationSelection: ...

    async def list_models(self) -> tuple[ChatModel, ...]: ...

    async def select_model(self, model_id: str) -> GenerationSelection: ...

    async def cycle_reasoning(self) -> GenerationSelection: ...
