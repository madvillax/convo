"""Rerank the hybrid candidate pool with a small, local cross-encoder."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from convo.core.contracts import Hit

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder


class Reranker:
    def __init__(self, name: str, min_score: float = -3.0) -> None:
        self.name, self.min_score = name, min_score
        self._model: CrossEncoder | None = None

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            from sentence_transformers import CrossEncoder
            from torch.nn import Identity

            model = None
            try:
                model = CrossEncoder(
                    self.name, local_files_only=True, max_length=512, activation_fn=Identity()
                )
            except OSError:
                pass
            if model is None:
                model = CrossEncoder(self.name, max_length=512, activation_fn=Identity())
            self._model = model
        return self._model

    def rerank(
        self, question: str, hits: list[Hit], limit: int = 5, *, filter_weak: bool = True
    ) -> list[Hit]:
        if not hits:
            return []
        scores = np.asarray(
            self.model.predict(
                [(question, hit.text) for hit in hits],
                batch_size=8,
                show_progress_bar=False,
                convert_to_numpy=True,
            ),
            dtype=np.float32,
        ).reshape(-1)
        if len(scores) != len(hits) or not np.isfinite(scores).all():
            raise ValueError("Reranker returned invalid scores")
        ranked = sorted(
            zip(hits, scores, strict=True), key=lambda item: float(item[1]), reverse=True
        )
        # Raw model logits are ranking scores, not calibrated probabilities.
        return [
            replace(hit, score=float(score))
            for hit, score in ranked
            if not filter_weak or float(score) >= self.min_score
        ][:limit]
