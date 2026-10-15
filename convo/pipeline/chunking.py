"""Convert reader documents into the application's small chunk contract."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llama_index.core.schema import Document

from convo.core.contracts import ChunkData

MAX_CHUNKS = 2_000


def split_documents(
    documents: list[Document], tokenizer: Callable[[str], list[int]]
) -> list[ChunkData]:
    """Split reader output using the embedding model's tokenizer and chunk size."""
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.core.schema import MetadataMode

    splitter = SentenceSplitter(
        chunk_size=512,
        chunk_overlap=64,
        tokenizer=tokenizer,
        include_metadata=False,
        include_prev_next_rel=False,
    )
    chunks: list[ChunkData] = []
    for section, document in enumerate(documents, 1):
        page = document.metadata.get("page_label")
        locator = f"page {page}" if page is not None else f"reader section {section}"
        for node in splitter.get_nodes_from_documents([document]):
            text = node.get_content(metadata_mode=MetadataMode.NONE).strip()
            if text:
                chunks.append(ChunkData(text=text, locator=locator))
                if len(chunks) > MAX_CHUNKS:
                    raise ValueError("File produced too many chunks")
    if not chunks:
        raise ValueError("File did not produce any chunks")
    return chunks
