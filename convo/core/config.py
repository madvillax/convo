import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EMBEDDING_DIMENSIONS = 1024


def user_settings_path() -> Path:
    """Return the private per-user settings file used by an installed CLI."""
    config_home = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "convo" / ".env"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    embedding_model: str
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    rerank_min_score: float = -3.0
    retrieval_candidates: int = 20


def load_environment() -> None:
    # Environment variables win. The user file makes an installed tool independent
    # of its read-only site-packages directory; the repository file remains useful
    # for contributors running from a checkout.
    load_dotenv(user_settings_path(), override=False)
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def load_settings() -> Settings:
    load_environment()
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("Set DATABASE_URL to a PostgreSQL/Psycopg URL")
    embedding_model = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    if embedding_model != "Qwen/Qwen3-Embedding-0.6B":
        raise ValueError("Changing the embedding model requires a dimension/schema review")
    rerank_min_score = float(os.getenv("RERANK_MIN_SCORE", "-3"))
    retrieval_candidates = int(os.getenv("RETRIEVAL_CANDIDATES", "20"))
    if not math.isfinite(rerank_min_score) or not 5 <= retrieval_candidates <= 50:
        raise ValueError("Use a finite RERANK_MIN_SCORE and RETRIEVAL_CANDIDATES between 5 and 50")
    return Settings(
        database_url=database_url,
        embedding_model=embedding_model,
        reranker_model=os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L6-v2"),
        rerank_min_score=rerank_min_score,
        retrieval_candidates=retrieval_candidates,
    )
