"""Read one selected file with LlamaIndex's file readers only."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from zipfile import ZipFile

if TYPE_CHECKING:
    from llama_index.core.schema import Document

SUPPORTED = {".txt", ".md", ".pdf", ".docx", ".csv", ".json", ".py", ".rst", ".log"}
MAX_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 500_000
MAX_DOCX_EXPANDED_BYTES = 50 * 1024 * 1024


def read_file(path: Path) -> list[Document]:
    """Load text and reader metadata for one file; never scan its directory."""
    if not path.is_file() or path.suffix.lower() not in SUPPORTED:
        raise ValueError("Choose a supported file")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("File exceeds 10 MB")
    if path.suffix.lower() == ".docx":
        with ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_DOCX_EXPANDED_BYTES:
                raise ValueError("Expanded DOCX is too large")

    from llama_index.core import SimpleDirectoryReader
    from llama_index.readers.file import PDFReader

    documents = SimpleDirectoryReader(
        input_files=[str(path)],
        encoding="utf-8",
        errors="strict",
        raise_on_error=True,
        # Keep PDF pages separate, preserving page_label metadata for sources.
        file_extractor={".pdf": PDFReader(return_full_document=False)},
    ).load_data()
    documents = [document for document in documents if document.text.strip()]
    if (
        not documents
        or sum(len(document.text) for document in documents) > MAX_EXTRACTED_CHARACTERS
    ):
        raise ValueError("Empty file or too much extracted text")
    return documents
