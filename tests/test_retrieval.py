from types import SimpleNamespace

import numpy as np
import pytest

from convo.core.contracts import Hit
from convo.db.chunks import reciprocal_rank_fusion
from convo.pipeline.reranking import Reranker


def test_rank_fusion_combines_both_searches_and_deduplicates_chunks():
    semantic = Hit("Semantic passage", "section 1", 0.1, 10)
    keyword = Hit("Keyword passage", "section 2", 0.9, 20)
    both = Hit("Appears in both searches", "section 3", 0.2, 30)
    result = reciprocal_rank_fusion([[semantic, both], [keyword, both]], limit=3)
    assert result[0].chunk_id == 30
    assert {hit.chunk_id for hit in result} == {10, 20, 30}
    assert len(reciprocal_rank_fusion([[semantic, semantic], [keyword]], 3)) == 2


def test_cross_encoder_reranks_filters_and_never_changes_citation_identity(monkeypatch):
    hits = [
        Hit("First passage", "page 1", 0.1, 1),
        Hit("Best passage", "page 2", 0.2, 2),
        Hit("Unrelated passage", "page 3", 0.3, 3),
    ]
    received = []

    def predict(pairs, **kwargs):
        received.extend(pairs)
        return np.array([1.0, 8.0, -9.0])

    reranker = Reranker("unused", min_score=-3)
    monkeypatch.setattr(reranker, "_model", SimpleNamespace(predict=predict))
    result = reranker.rerank("Question", hits)
    assert [hit.chunk_id for hit in result] == [2, 1]
    assert result[0].score == 8
    assert result[0].text == hits[1].text
    assert received == [("Question", hit.text) for hit in hits]


def test_reranker_handles_empty_results_and_rejects_nonfinite_scores(monkeypatch):
    reranker = Reranker("unused")
    assert reranker.rerank("Question", []) == []
    monkeypatch.setattr(
        reranker, "_model", SimpleNamespace(predict=lambda *_args, **_kwargs: np.array([np.nan]))
    )
    with pytest.raises(ValueError, match="invalid scores"):
        reranker.rerank("Question", [Hit("Text", "section 1", 0.1)])
