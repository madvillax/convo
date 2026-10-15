"""Generate Qwen3 vectors locally with sentence-transformers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from convo.core.config import EMBEDDING_DIMENSIONS


class Embedder:
    def __init__(self, model_name: str) -> None:
        self.name = model_name
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            # A cached model should not make HTTP checks on every new CLI session.
            model = None
            try:
                model = SentenceTransformer(self.name, local_files_only=True)
            except (OSError, TypeError):
                # A partial ST cache can return an empty pooling config and raise
                # TypeError instead of OSError. Let the Hub fill missing assets.
                pass
            # Leave the exception scope first so a partial model and its traceback
            # can be released before allocating the replacement weights.
            if model is None:
                model = SentenceTransformer(self.name)
            self._model = model
            self._model.max_seq_length = 2048
        return self._model

    @property
    def signature(self) -> str:
        # Bump v1 after changing reader behavior, tokenizer, prompts or model revision.
        return f"{self.name}:qwen-tokenizer:512tokens:64overlap:normalized:2048max:v1"

    def tokenize(self, text: str) -> list[int]:
        return list(self.model.tokenizer.encode(text, add_special_tokens=False))

    def documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            raise ValueError("Cannot embed an empty chunk list")
        vectors = np.asarray(
            self.model.encode(
                texts,
                batch_size=8,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )
        if vectors.shape != (len(texts), EMBEDDING_DIMENSIONS):
            raise ValueError("Unexpected embedding dimensions")
        if not np.isfinite(vectors).all():
            raise ValueError("Invalid embeddings")
        return vectors.tolist()

    def query(self, question: str) -> list[float]:
        if not question.strip():
            raise ValueError("Cannot embed an empty question")
        vector = np.asarray(
            self.model.encode(
                [question],
                prompt_name="query",
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )[0],
            dtype=np.float32,
        )
        if vector.shape != (EMBEDDING_DIMENSIONS,) or not np.isfinite(vector).all():
            raise ValueError("Unexpected query embedding")
        return vector.tolist()
