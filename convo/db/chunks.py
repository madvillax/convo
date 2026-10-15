import math
import re
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from convo.core.config import EMBEDDING_DIMENSIONS
from convo.core.contracts import ChunkData, Hit
from convo.db.models import ChunkRow, DocumentRow


def keyword_query(question: str) -> str:
    """Natural questions use optional content terms rather than requiring every word."""
    ignored = set(
        "a an the what when where why who which how is are was were do does did can could "
        "would should will you me i we it this that these those file document please tell "
        "explain describe summarize summarise about in on of for to and or".split()
    )
    terms = dict.fromkeys(
        term.casefold()
        for term in re.findall(r"\w+(?:[-.]\w+)*", question)
        if term.casefold() not in ignored
    )
    return " OR ".join(list(terms)[:32]) or question


def replace_chunks(
    session: Session,
    document_id: UUID,
    chunks: list[ChunkData],
    vectors: list[list[float]],
) -> None:
    if not chunks or len(chunks) != len(vectors):
        raise ValueError("Chunks and vectors do not match")
    if any(len(vector) != EMBEDDING_DIMENSIONS for vector in vectors):
        raise ValueError("Incorrect embedding dimensions")
    if any(not chunk.text.strip() or not chunk.locator for chunk in chunks):
        raise ValueError("Chunks need text and a source locator")
    if any(not math.isfinite(value) for vector in vectors for value in vector):
        raise ValueError("Embeddings must contain finite values")
    session.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))
    session.add_all(
        [
            ChunkRow(
                document_id=document_id,
                ordinal=i,
                text=chunk.text,
                locator=chunk.locator,
                embedding=vector,
            )
            for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
    )


def reciprocal_rank_fusion(rankings: list[list[Hit]], limit: int = 20) -> list[Hit]:
    """Fuse lexical and semantic ranks without comparing incompatible raw scores."""
    scores: dict[object, float] = {}
    hits: dict[object, Hit] = {}
    for ranking in rankings:
        seen = set()
        for rank, hit in enumerate(ranking, 1):
            key = hit.chunk_id if hit.chunk_id is not None else (hit.text, hit.locator)
            if key in seen:
                continue
            seen.add(key)
            hits[key] = hit
            scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
    # Stable insertion order breaks equal scores deterministically.
    return [hits[key] for key in sorted(scores, key=lambda key: -scores[key])[:limit]]


def retrieve(
    session: Session,
    document_id: UUID,
    signature: str,
    query: list[float],
    question: str,
    limit: int = 20,
    *,
    overview: bool = False,
) -> list[Hit]:
    document = session.get(DocumentRow, document_id)
    if document is None or document.index_signature != signature:
        raise ValueError("Missing or outdated index; select the file again")
    if len(query) != EMBEDDING_DIMENSIONS or any(not math.isfinite(value) for value in query):
        raise ValueError("Invalid query embedding")
    if not 1 <= limit <= 50 or not question.strip():
        raise ValueError("Use a non-empty query and a candidate limit between 1 and 50")
    distance = ChunkRow.embedding.cosine_distance(query).label("distance")
    columns = (ChunkRow.id, ChunkRow.text, ChunkRow.locator, distance)
    if overview:
        # Broad summaries need coverage, not a passage ranker's QA relevance cutoff.
        rows = list(
            session.execute(
                select(*columns)
                .where(ChunkRow.document_id == document_id)
                .order_by(ChunkRow.ordinal)
            )
        )
        size = min(limit, len(rows))
        indices = [round(index * (len(rows) - 1) / max(1, size - 1)) for index in range(size)]
        return [
            Hit(rows[index].text, rows[index].locator, float(rows[index].distance), rows[index].id)
            for index in indices
        ]
    semantic = (
        select(*columns)
        .where(ChunkRow.document_id == document_id)
        .order_by(distance, ChunkRow.ordinal)
        .limit(limit)
    )
    lexical_query = func.websearch_to_tsquery("english", keyword_query(question))
    lexical_rank = func.ts_rank_cd(ChunkRow.search_vector, lexical_query)
    lexical = (
        select(*columns)
        .where(
            ChunkRow.document_id == document_id,
            ChunkRow.search_vector.op("@@")(lexical_query),
        )
        .order_by(lexical_rank.desc(), ChunkRow.ordinal)
        .limit(limit)
    )
    rankings = [
        [
            Hit(text, locator, float(distance), identity)
            for identity, text, locator, distance in session.execute(statement)
        ]
        for statement in (semantic, lexical)
    ]
    return reciprocal_rank_fusion(rankings, limit)
