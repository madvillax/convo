"""Values passed between ingestion, providers, and repositories."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkData:
    text: str
    locator: str


@dataclass(frozen=True)
class Hit:
    text: str
    locator: str
    distance: float
