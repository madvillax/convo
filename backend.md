# Build the backend: PostgreSQL + pgvector + SQLAlchemy + Alembic

The Python TUI is ready. The backend files are small scaffolds, organized by responsibility. The code in this guide is reference code to put into those files yourself. The application still runs with `ShellBackend`; it does not connect to PostgreSQL or make model requests yet.

Your stack:

| Responsibility | Tool |
| --- | --- |
| Interface | Textual |
| Dependencies, environments, commands | uv |
| Formatting and lint | Ruff |
| Type checking | ty |
| Database | PostgreSQL with pgvector |
| ORM and transactions | SQLAlchemy 2 |
| Schema changes | Alembic |
| Readers and chunkers only | LlamaIndex |
| Local embeddings | Qwen3-Embedding-0.6B via sentence-transformers |
| OpenAI generation | Existing ChatGPT account through Sign in with ChatGPT (OAuth), then the Responses API |

## What the current app uses for chat

The TUI renders the transcript in Textual widgets. `chat/sessions.py` holds one `ChatSession` in memory, including its temporary ID, selected document, and completed `Message` turns. `chat/history.py` appends a turn only after a successful answer. The backend contract receives the history tuple with each question. Choosing another file starts a fresh session; `/clear` empties history while keeping the file, and `/reset` also detaches the file. Closing the app loses the session and conversation.

The active `ChatSession` ID is temporary; sessions and messages are not persisted to PostgreSQL. A selected document's `Document.id` identifies an indexed file snapshot; it is not a chat ID. The SQLAlchemy `Session` introduced later is a short-lived database unit of work for writes or retrieval. It is separate from the conversation, and the guide closes it before making a model request.

The TUI keeps completed turns in memory and passes them to the ChatGPT adapter. OpenAI's ChatGPT-plan flow requires `stream=true` and `store=false`; the first backend version can collect its stream and return one complete `Answer` to the current TUI. The TUI does not yet render token-by-token deltas. Successful question/answer pairs enter history after generation; failed requests do not. There is no tool-calling loop: retrieval is ordinary Python before generation, so the model does not need a retrieval tool.

The current `chat/streaming.py` boundary is for collecting a provider stream into the complete `Answer` the TUI accepts; it does not render token-by-token updates. Add durable conversations when you want resume-after-restart. Add model tools and an agent loop only when you have a concrete action the model should choose. File retrieval is ordinary Python in this app, so tool calling is not needed for RAG.

`/login` is for OpenAI's documented **Sign in with ChatGPT** flow. It opens the user's browser, receives an OAuth callback on loopback, validates the grant, and saves credentials locally. It does not ask for an OpenAI API key and does not import ChatGPT conversations. ChatGPT-plan use is currently documented for eligible open-source and local apps; commercial eligibility is separate. Read OpenAI's [open-source integration guide](https://developers.openai.com/siwc/token-sharing-open-source) and [terms](https://openai.com/policies/sign-in-with-chatgpt-terms/) before distributing the app.

**One build order:** setup → PostgreSQL and SQLAlchemy → Alembic → file reading and chunking → embeddings → database queries → ChatGPT sign-in and generation → RAG flow → TUI connection.

## 1. Understand the folders and install the backend dependencies

There is no `src/` package directory. The importable package is `convo/` at the project root:

```text
convo/                            # project root
├── pyproject.toml
├── uv.lock
├── .env.example
├── alembic.ini
├── migrations/
│   ├── env.py                    # scaffold: migration configuration
│   ├── script.py.mako            # template for new revisions
│   └── versions/                 # your versioned schema changes
├── convo/                        # Python package; no src/convo wrapper
│   ├── __init__.py
│   ├── __main__.py               # CLI entry and dependency wiring
│   ├── core/
│   │   ├── config.py             # environment-backed settings
│   │   ├── contracts.py          # shared values and TUI/backend protocols
│   │   └── exceptions.py         # expected backend errors shown by the TUI
│   ├── ui/
│   │   ├── app.py                # transcript, commands, async workers
│   │   ├── files.py              # /file picker
│   │   └── theme.tcss            # appearance
│   ├── auth/
│   │   ├── chatgpt.py            # Sign in with ChatGPT, token refresh
│   │   └── credentials.py        # OS keyring boundary and adapter
│   ├── providers/
│   │   ├── base.py               # generation contract shared by adapters
│   │   └── openai.py             # ChatGPT Responses API adapter
│   ├── chat/
│   │   ├── service.py            # RAG use case and TUI backend adapter
│   │   ├── sessions.py           # one process-local chat session
│   │   ├── history.py            # successful-turn history helper
│   │   ├── streaming.py          # collect provider events for complete answers
│   │   └── shell.py              # UI-only adapter used until backend is connected
│   ├── rag/
│   │   ├── ingestion.py          # read only the selected file
│   │   ├── chunking.py           # LlamaIndex SentenceSplitter only
│   │   ├── embeddings.py         # local Qwen3 embeddings
│   │   └── index.py              # file indexing and document-scoped retrieval
│   └── db/
│       ├── base.py               # SQLAlchemy metadata for Alembic
│       ├── models.py             # document and chunk rows
│       ├── session.py            # engine and session factory
│       └── repositories/
│           ├── documents.py      # document-row writes
│           ├── chunks.py         # replace chunks and pgvector search
│           └── conversations.py  # future durable conversation history
└── tests/test_ui.py
```

Each folder has one job. `core/` holds shared settings and interfaces. `auth/` handles the user's ChatGPT login. `providers/` makes model requests. `chat/` keeps the active session and joins retrieval with generation. `rag/` reads, chunks, embeds, indexes, and searches the selected file. `db/` owns SQLAlchemy setup and table mappings. `db/repositories/` contains Python query functions that read and write rows through a supplied SQLAlchemy session; it is not a second place where data is stored. The TUI imports only the `Backend` protocol and session value; it does not import provider or database code.

The important seams are `Backend` (what the TUI calls), `RagBackend` (the use case that joins the parts), `DocumentIndex` (file preparation and scoped search), `ChatProvider` (generation), and `CredentialStore` (secure token storage). `providers/base.py` defines the small generation contract; `providers/openai.py` is its only adapter in this ChatGPT-only version. A SQLAlchemy repository contains database statements; the `db/` package defines tables and makes sessions. Ingestion calls the reader/chunker and repositories; the repository does not run ingestion.

`db/repositories/conversations.py` is the intended seam for durable chat history. The current `ChatSession` still keeps messages in memory, and this guide does not yet add conversation tables or migrations. Implement that repository together with `ChatSessionRow` and `MessageRow` only when you want conversations to survive app restarts.

This project uses one provider: ChatGPT. There is no Gemini adapter. ChatGPT may support function tools, but this app does not need them: the user selects a file and Python performs retrieval directly before generation. There is no `tools/` or `agent/` package in this first version. Add those packages later only if you define specific model-callable actions.

Files with responsibility comments are scaffolds, not working database/provider implementations.

```sh
uv sync --python 3.12
# When you start building the backend:
uv sync --extra backend
```

The backend extra contains SQLAlchemy, Alembic, pgvector, Psycopg 3, HTTPX, dotenv, LlamaIndex core/file readers, docx2txt, sentence-transformers, Transformers, the OpenAI SDK, a keyring adapter, and JWT verification support. The shell runs without that extra. Installing it includes PyTorch; loading Qwen later downloads its weights.

Use uv for every project command:

```sh
uv run ruff format .
uv run ruff check .
uv run --extra backend ty check
uv run pytest -q
```

The scaffold references optional backend packages, so type-check it with `uv run --extra backend ty check`. Ruff formats/lints; ty checks types; neither proves that a database query or model call works. Their versions are locked in `uv.lock`.

LlamaIndex's scope ends after `SimpleDirectoryReader` and `SentenceSplitter`. Do not add `VectorStoreIndex`, query engines, chat engines, LlamaIndex vector stores, or its LLM/embedding integrations. SQLAlchemy owns persistence, pgvector owns search, and `chat/service.py` owns the chat use case. Some framework internals arrive transitively with `llama-index-core`; that is not a reason to use them.

**Checkpoint:** `uv run convo` still launches the shell; the four checks above pass.

## 2. Prepare PostgreSQL, pgvector and configuration

Use an existing PostgreSQL instance with the pgvector extension installed, or start a local instance. For a local Podman setup, create a dedicated container and volume:

```sh
podman run --name convo-postgres \
  -e POSTGRES_USER=convo \
  -e POSTGRES_PASSWORD=convo \
  -e POSTGRES_DB=convo \
  -p 127.0.0.1:5432:5432 \
  -v convo-postgres-data:/var/lib/postgresql/data \
  -d pgvector/pgvector:pg17
podman exec convo-postgres pg_isready -U convo -d convo
```

Run these yourself only if you want this local database and port 5432 is available. Podman must already be running. Use `podman start convo-postgres` for subsequent sessions. The sample credential is for local development. For an existing or hosted database, use its URL, SSL requirements and administrator-approved extension setup.

Copy `.env.example` to `.env` in the project root:

```dotenv
DATABASE_URL=postgresql+psycopg://convo:convo@localhost:5432/convo
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
```

The `postgresql+psycopg` prefix selects SQLAlchemy's Psycopg 3 driver. Percent-encode special characters in a URL password. Enable `vector` through the first migration in step 4; a PostgreSQL server without the extension's installed files cannot create it.

Replace `convo/core/config.py`:

```python
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
EMBEDDING_DIMENSIONS = 1024


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    embedding_model: str


def load_settings() -> Settings:
    # Independent of the user's document browsing directory; env vars take priority.
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("Set DATABASE_URL to a PostgreSQL/Psycopg URL")
    embedding_model = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    if embedding_model != "Qwen/Qwen3-Embedding-0.6B":
        raise ValueError("Changing the embedding model requires a dimension/schema review")
    return Settings(
        database_url=database_url,
        embedding_model=embedding_model,
    )
```

OpenAI credentials do not belong in `.env`: `/login` stores the user's SIWC credentials in the operating-system credential store, with non-secret account metadata in the user config directory. Do not print the Settings object because it holds secrets. This `.env` path is for the editable source install; use a user config directory for distributed settings.

**Checkpoint:** load settings and connect to PostgreSQL without printing the URL/password. Check `pg_available_extensions` for `vector`; if missing, install pgvector on the server first. No application tables exist yet.

## 3. Define SQLAlchemy models and sessions

`db/base.py` owns shared metadata, `db/models.py` maps the two tables, and `db/session.py` creates connections. `Document` in `core/contracts.py` is the value sent to the TUI; `DocumentRow` is the stored database record.

Replace `convo/db/base.py`:

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
```

Replace `convo/db/models.py`:

```python
from uuid import UUID

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from convo.core.config import EMBEDDING_DIMENSIONS
from convo.db.base import Base


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    index_signature: Mapped[str] = mapped_column(Text, nullable=False)


class ChunkRow(Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("document_id", "ordinal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(EMBEDDING_DIMENSIONS), nullable=False)
```

Keep both models together because there are only two tables. The unique `(document_id, ordinal)` constraint supports document-scoped lookup. Start with exact pgvector search.

Replace `convo/db/session.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from convo.core.config import Settings


def make_session_factory(settings: Settings):
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        echo=False,
        connect_args={"connect_timeout": 10},
    )
    return engine, sessionmaker(engine, expire_on_commit=False)
```

Use synchronous SQLAlchemy in `asyncio.to_thread` from `rag/index.py`. Each operation gets its own session. Close the session before making a ChatGPT request. Alembic manages schema changes; avoid creating tables at TUI startup. See [SQLAlchemy session basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html).

There are no chat-session or message tables in this version. Chat history stays in the process-local `ChatSession`; PostgreSQL stores the indexed document snapshot and chunks only.

**Checkpoint:** importing `db/models.py` registers `documents` and `chunks` in `Base.metadata.tables` without connecting to PostgreSQL. Create the engine/session factory separately.

## 4. Create and apply the first Alembic migration

`alembic.ini`, the revision template, and the migration folders already exist. `migrations/env.py` intentionally stops with a clear scaffold error until you replace it; there are no revisions or applied migrations yet. Do not run `alembic init` over these existing files.

Replace `migrations/env.py`:

```python
from alembic import context
from sqlalchemy import create_engine, pool

from convo.core.config import load_settings
from convo.db import models as _models
from convo.db.base import Base

config = context.config
settings = load_settings()
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Make the first revision **without autogenerate**, so you can explicitly enable pgvector before creating its column:

```sh
uv run --extra backend alembic revision -m "create rag tables"
```

Keep the generated `revision`, `down_revision`, `branch_labels` and `depends_on` values. Add `from pgvector.sqlalchemy import VECTOR`, then replace the two functions in that generated file:

```python
# Keep these imports alongside the generated revision identifiers:
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("index_signature", sa.Text(), nullable=False),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("embedding", VECTOR(1024), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "ordinal"),
    )


def downgrade() -> None:
    op.drop_table("chunks")
    op.drop_table("documents")
    # Retain the extension: another application may share it.
```

Review the revision, then apply it to your development database:

```sh
uv run --extra backend alembic upgrade head
uv run --extra backend alembic current
uv run --extra backend alembic check
```

On a managed server, an administrator may need to enable the extension first. Do not connect to an unrelated production database for these learning steps. A downgrade deletes the tables and their indexed data.

For later model changes:

```sh
uv run --extra backend alembic revision --autogenerate -m "describe your schema change"
# Read and correct the generated revision before applying it.
uv run --extra backend alembic upgrade head
```

Autogenerate is a draft: extension creation is not automatically inferred, and custom vector types may require adding a pgvector import or rewriting their representation to `VECTOR(n)`. Review every generated revision. See [Alembic's tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html).

**Checkpoint:** PostgreSQL contains `alembic_version`, `documents`, `chunks`, and an enabled `vector` extension. `alembic check` reports no ORM/schema difference.

## 5. Use LlamaIndex for readers and chunking only

Add `read_file()` to `convo/rag/ingestion.py` and `split_documents()` to `convo/rag/chunking.py`. Keep each file's imports with its function.

```python
from pathlib import Path
from zipfile import ZipFile

from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import PDFReader

SUPPORTED = {".txt", ".md", ".pdf", ".docx", ".csv", ".json", ".py", ".rst", ".log"}
MAX_BYTES = 10 * 1024 * 1024


def read_file(path: Path):
    if not path.is_file() or path.suffix.lower() not in SUPPORTED:
        raise ValueError("Choose a supported file")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("File exceeds 10 MB")
    if path.suffix.lower() == ".docx":
        with ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                raise ValueError("Expanded DOCX is too large")
    documents = SimpleDirectoryReader(
        input_files=[str(path)],
        encoding="utf-8",
        errors="strict",
        raise_on_error=True,
        # Keep PDF pages separate, preserving page_label metadata for sources.
        file_extractor={".pdf": PDFReader(return_full_document=False)},
    ).load_data()
    documents = [doc for doc in documents if doc.text.strip()]
    if not documents or sum(len(doc.text) for doc in documents) > 500_000:
        raise ValueError("Empty file or too much extracted text")
    return documents
```

The reader loads only the selected path; it does not scan the whole current directory. File reader integrations are supplied by `llama-index-readers-file`; `docx2txt` is included for its DOCX reader. PDFs with only scanned images require OCR, which this baseline does not provide. Complex file parsers can consume large resources even under a byte limit; isolate them in a process with limits if you later accept untrusted files.

Put this chunking function in `convo/rag/chunking.py`:

```python
from collections.abc import Callable

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import MetadataMode

from convo.core.contracts import ChunkData


def split_documents(documents, tokenizer: Callable[[str], list[int]]) -> list[ChunkData]:
    splitter = SentenceSplitter(
        chunk_size=512,
        chunk_overlap=64,
        tokenizer=tokenizer,
        include_metadata=False,
        include_prev_next_rel=False,
    )
    chunks = []
    for section, document in enumerate(documents, 1):
        page = document.metadata.get("page_label")
        locator = f"page {page}" if page is not None else f"reader section {section}"
        for node in splitter.get_nodes_from_documents([document]):
            text = node.get_content(metadata_mode=MetadataMode.NONE).strip()
            if text:
                chunks.append(ChunkData(text=text, locator=locator))
    if not chunks or len(chunks) > 2000:
        raise ValueError("No chunks or too many chunks")
    return chunks
```

Pass Qwen's tokenizer in step 9 so the 512-token window uses the embedding model's tokenization. `include_metadata=False` avoids counting/embedding full filesystem metadata as text. We immediately convert nodes into your own `ChunkData` values; other layers don't depend on LlamaIndex nodes.

A PDF page label is a real reader locator. A text/DOCX reader section is coarse: it does **not** mean a line, paragraph or Word page. Do not invent finer citations. Add custom reader metadata later if you need that precision. [Reader documentation](https://developers.llamaindex.ai/python/framework/module_guides/loading/simpledirectoryreader/) and [SentenceSplitter documentation](https://developers.llamaindex.ai/python/framework/module_guides/loading/node_parsers/modules/) explain these APIs.

**Checkpoint:** read a Markdown file and a text PDF. Inspect extracted text and metadata, then inspect the resulting chunks. Every chunk has content and an honest locator. Empty extraction fails before database writes.

## 6. Add Qwen3 embeddings directly

Replace `convo/rag/embeddings.py`:

```python
import numpy as np
from sentence_transformers import SentenceTransformer

from convo.core.config import EMBEDDING_DIMENSIONS


class Embedder:
    def __init__(self, model_name: str):
        self.name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = SentenceTransformer(self.name)
            self._model.max_seq_length = 2048
        return self._model

    @property
    def signature(self) -> str:
        # Bump v1 after changing reader behavior, tokenizer, prompts or model revision.
        return f"{self.name}:qwen-tokenizer:512tokens:64overlap:normalized:2048max:v1"

    def documents(self, texts: list[str]) -> list[list[float]]:
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
```

Documents are plain text; queries use `prompt_name="query"`. The [official Qwen model card](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) documents that query prompt and the 1,024-dimensional default for the 0.6B model. Keep the model's output dimension consistent with `VECTOR(1024)`. Changing model size/dimensions requires a reviewed migration and reindexing; do not mix incompatible embeddings.

No LlamaIndex embedding wrapper is involved. Lazy model loading happens in the threaded service. Before launching the finished backend TUI, prewarm the model outside it so first-time download output doesn't interrupt the screen.

**Checkpoint:** two passages produce two 1,024-dimensional normalized vectors. A question about one passage ranks it higher by cosine similarity. No ChatGPT request is needed for this check.

## 7. Add document-scoped pgvector queries

Repository functions receive a SQLAlchemy `Session`; `DocumentIndex` decides when to begin and commit the transaction.

Put `upsert_document()` in `convo/db/repositories/documents.py`:

```python
from pathlib import Path
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from convo.db.models import DocumentRow


def upsert_document(
    session: Session,
    document_id: UUID,
    path: Path,
    content_hash: str,
    signature: str,
) -> None:
    values = {
        "id": document_id,
        "source_path": str(path),
        "content_hash": content_hash,
        "index_signature": signature,
    }
    statement = insert(DocumentRow).values(**values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[DocumentRow.id],
            set_={"index_signature": signature},
        )
    )
    # The upsert locks the document row until commit, serializing replacement.
```

Put `replace_chunks()` and `retrieve()` in `convo/db/repositories/chunks.py`:

```python
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from convo.core.config import EMBEDDING_DIMENSIONS
from convo.core.contracts import ChunkData, Hit
from convo.db.models import ChunkRow, DocumentRow


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


def retrieve(
    session: Session,
    document_id: UUID,
    signature: str,
    query: list[float],
    limit=5,
) -> list[Hit]:
    document = session.get(DocumentRow, document_id)
    if document is None or document.index_signature != signature:
        raise ValueError("Missing or outdated index; select the file again")
    if len(query) != EMBEDDING_DIMENSIONS:
        raise ValueError("Incorrect query dimensions")
    distance = ChunkRow.embedding.cosine_distance(query).label("distance")
    statement = (
        select(ChunkRow.text, ChunkRow.locator, distance)
        .where(ChunkRow.document_id == document_id)
        .order_by(distance)
        .limit(limit)
    )
    return [
        Hit(text=text, locator=locator, distance=float(value))
        for text, locator, value in session.execute(statement)
    ]
```

Cosine **distance sorts ascending**; lower is closer. It is not a confidence percentage. Always constrain `document_id` before ranking, so asking about one file can't return another file's chunks. SQLAlchemy binds the vector and identifiers as parameters. The [pgvector Python SQLAlchemy guide](https://github.com/pgvector/pgvector-python#sqlalchemy) documents `VECTOR` and `cosine_distance`.

Start with exact search for a small document. If you later add an HNSW index, use the cosine operator class `vector_cosine_ops`, review filtered approximate-query recall, and benchmark before switching. Do not add an ANN index just because the column is a vector.

**Checkpoint:** insert two documents containing conflicting facts inside separate transactions. Searching each ID returns only its own rows. A failed chunk replacement rolls back without exposing a half-built document. Inspect actual PostgreSQL results, not just generated SQL.

## 8. Add `/login` and ChatGPT generation

OpenAI has two separate pieces here: the user authorizes Convo with **Sign in with ChatGPT**, and your Python code calls the Responses API with the resulting access token. The official OpenAI Python SDK can send that OAuth token as its bearer credential. This project intentionally has no `OPENAI_API_KEY` mode. Current OpenAI docs make ChatGPT-plan usage available to eligible open-source and local apps; check the [current eligibility and requirements](https://developers.openai.com/siwc/quickstart) before distributing Convo.

### 8.1 Implement the `/login` authorization flow

In `convo/auth/chatgpt.py`, implement the official [open-source Sign in with ChatGPT flow](https://developers.openai.com/siwc/token-sharing-open-source/sign-in). `/login` should start a loopback HTTP callback on `127.0.0.1`, open the system browser with `webbrowser.open()`, wait for the callback, then return an account label to the TUI.

The flow has several security checks; keep them together in `ChatGPTAuth`:

1. Generate one stable `ext_agent_host_id` for this machine and save it under the app's user config directory. For a UUID host ID, use `urn:uuid:<uuid4>`. For each login attempt, generate fresh `state`, OIDC `nonce`, and PKCE verifier/challenge. Bind them to a short-lived pending transaction.
2. For first-time registration, open `https://auth.openai.com/api/accounts/authorize` with `client_id=dynamic_agent_client`, `agent_name_hint=convo`, and the host ID. For later sign-ins, use that account's issued `client_id`. Request `openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`, set `resource=https://api.openai.com/v1`, and use `code_challenge_method=S256`.
3. Use the exact loopback `redirect_uri` and port in both authorization and token exchange. Validate `state`, handle denial/error callbacks, and require the issued `client_id` on first registration.
4. Exchange the code at `https://auth.openai.com/api/accounts/oauth/token` with a form-encoded authorization-code grant, `client_id`, `code`, `code_verifier`, `redirect_uri`, and `resource`. The public local-client flow does not use a client secret.
5. Verify the ID-token signature using the `jwks_uri` from OpenAI's [OIDC discovery document](https://auth.openai.com/.well-known/openid-configuration). Check issuer, audience, expiry, and nonce. Check the granted scopes include `chatgpt.tokens.use.direct`; identity-only sign-in is not enough to call models.
6. Store the access and refresh tokens, ID token, issued client ID, verified subject, scopes, and expiry locally. Use the operating system keyring for secrets and a small file under the user config directory for non-secret metadata. Refresh and replace the rotating refresh token together. Never save credentials to `.env`, PostgreSQL, the selected project folder, or logs.

The URL-building and code-exchange core can look like this. The callback server must still enforce a timeout, accept only one matching `state`, reject OAuth errors, and keep the callback on loopback:

```python
import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


def create_authorization_attempt(
    redirect_uri: str,
    host_id: str,
    issued_client_id: str | None = None,
    id_token_hint: str | None = None,
) -> tuple[str, str, str, str]:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    client_id = issued_client_id or "dynamic_agent_client"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge.decode().rstrip("="),
        "code_challenge_method": "S256",
        "ext_agent_host_id": host_id,
    }
    if issued_client_id is None:
        params["agent_name_hint"] = "convo"
    if id_token_hint:
        params["id_token_hint"] = id_token_hint
    return f"{AUTHORIZE_URL}?{urlencode(params)}", state, nonce, verifier


async def exchange_code(code: str, client_id: str, redirect_uri: str, verifier: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
                "resource": RESOURCE,
            },
        )
        response.raise_for_status()
        return response.json()
```

On first registration, take the newly issued `client_id` from the validated callback and use it for code exchange; do not exchange with `dynamic_agent_client`. Keep `nonce` and `state` in memory for the one attempt, and validate the ID token before making the keyring record active.

Do not collect passwords or browser cookies. Do not proxy or pool user plan usage. OpenAI's [SIWC terms](https://openai.com/policies/sign-in-with-chatgpt-terms/) require requests to come from the user's local runtime or a remote runtime they control, and token storage to stay local and under the user's control.

### 8.2 Call OpenAI with the connected account

This is the official Sign in with ChatGPT flow: `/login` opens the system browser, receives an OAuth callback on loopback, validates and stores the grant, and then the OpenAI SDK uses the access token for Responses API requests. It does not automate ChatGPT's website or import its conversation history. The SIWC inference contract currently requires `store=False` and `stream=True`, uses the public Responses API, and sends history in each request. It does not allow `previous_response_id` over HTTP and does not accept several standard Responses fields; follow the [preview limits](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations). Convo's TUI accepts a completed `Answer`, so put the stream collector in `chat/streaming.py` and return final text only after `response.completed`:

```python
from openai import AsyncOpenAI


async def complete_chatgpt(
    access_token: str, model: str, instructions: str, input_items: list[dict]
):
    async with AsyncOpenAI(
        api_key=access_token,  # SIWC OAuth token; never an OpenAI API key
        base_url="https://api.openai.com/v1",
        max_retries=0,
    ) as client:
        stream = await client.responses.create(
            model=model,
            instructions=instructions,
            input=input_items,
            store=False,
            stream=True,
        )
        text: list[str] = []
        completed = False
        async for event in stream:
            if event.type == "response.output_text.delta":
                text.append(event.delta)
            elif event.type == "response.failed":
                error = event.response.error
                raise RuntimeError(error.code if error else "OpenAI response failed")
            elif event.type == "response.completed":
                completed = True
        if not completed:
            raise RuntimeError("OpenAI stream ended before response.completed")
    return "".join(text)
```

Build `input_items` from the last few local `Message` values plus the current question and numbered excerpts. Put the safety prompt in `instructions`; don't add a `system` role item. Use a model returned by the signed-in account's model list. OpenAI does not provide Convo the user's ChatGPT conversation history, and `store=False` means Convo remains responsible for its own history.

### 8.3 Keep the ChatGPT adapter focused

Implement `ChatGPTProvider.answer()` in `providers/openai.py` using the `complete_chatgpt()` helper from `chat/streaming.py`:

1. Ask `ChatGPTAuth.access_token()` for a valid grant; refresh it if needed. If no grant exists, raise `BackendNotConnected("Connect your ChatGPT account with /login")`.
2. Discover the signed-in account's available models using the official model-list flow, then select an eligible model. Keep the selected model in local account metadata rather than assuming a fixed model is available to everyone.
3. Number the retrieved hits as `[1]`, `[2]`, and so on. Bound excerpt length and history before building `input_items`. Include the current question exactly once.
4. Set `instructions` to answer only from the provided evidence, cite its numbered excerpts, treat document text as data, and acknowledge when the file lacks an answer.
5. Call `complete_chatgpt()`. Reject empty output and citation IDs that do not match the excerpts sent. Construct `Answer(text, sources)` with real filename/locator labels and excerpts from those hits.

The adapter accepts `filename`, `question`, local `history`, and retrieved `hits`; it owns the model request and citation validation. `DocumentIndex` retrieves the evidence, and `RagBackend` passes it to this adapter.

Citation validation checks IDs, not whether every claim is supported. Review answers against evidence and test unrelated questions and instructions embedded in files. No filesystem writes or document instructions are executed by this RAG flow.

**Checkpoint:** `/login` opens the browser, validates the callback and granted scope, and stores tokens in the local keyring. A ChatGPT request succeeds only after a completed stream. Answers cite only retrieved excerpt IDs; logs and UI errors never reveal credentials.

## 9. Connect the document and chat features

### 9.1 Implement the document index

`rag/index.py` owns the file-to-vector pipeline and document-scoped retrieval. It calls the reader, chunker, embedder, and database repositories; it does not contain SQL statements. Replace `convo/rag/index.py`:

```python
import asyncio
import hashlib
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from convo.core.config import Settings
from convo.core.contracts import Document, Hit
from convo.db.repositories.chunks import replace_chunks, retrieve
from convo.db.repositories.documents import upsert_document
from convo.db.session import make_session_factory
from convo.rag.embeddings import Embedder
from convo.rag.chunking import split_documents
from convo.rag.ingestion import MAX_BYTES, read_file


class DocumentIndex:
    def __init__(self, settings: Settings):
        self.engine, self.sessions = make_session_factory(settings)
        self.embedder = Embedder(settings.embedding_model)
        self.lock = asyncio.Lock()

    def _prepare(self, path: Path) -> Document:
        path = path.resolve(strict=True)
        before = path.stat()
        if before.st_size > MAX_BYTES:
            raise ValueError("File exceeds the size limit")
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("File grew past the size limit")
        content_hash = hashlib.sha256(raw).hexdigest()
        documents = read_file(path)
        tokenizer = self.embedder.model.tokenizer
        chunks = split_documents(
            documents,
            tokenizer=lambda text: tokenizer.encode(text, add_special_tokens=False),
        )
        vectors = self.embedder.documents([chunk.text for chunk in chunks])
        after = path.stat()
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            raise ValueError("File changed during indexing; select it again")
        signature = self.embedder.signature
        # Snapshot identity: different content/recipe gets a different ID.
        document_id = uuid5(NAMESPACE_URL, f"{path}\n{content_hash}\n{signature}")
        # All parsing/model work finishes BEFORE opening the write transaction.
        with self.sessions.begin() as session:
            upsert_document(session, document_id, path, content_hash, signature)
            replace_chunks(session, document_id, chunks, vectors)
        return Document(id=str(document_id), path=path)

    async def prepare(self, path: Path) -> Document:
        async with self.lock:
            return await asyncio.to_thread(self._prepare, path)

    def _retrieve(self, document: Document, question: str) -> list[Hit]:
        vector = self.embedder.query(question)
        with self.sessions() as session:
            return retrieve(session, UUID(document.id), self.embedder.signature, vector)

    async def search(self, document: Document, question: str) -> list[Hit]:
        if not question.strip() or len(question) > 4000:
            raise ValueError("Use a question between 1 and 4,000 characters")
        async with self.lock:
            return await asyncio.to_thread(self._retrieve, document, question)

    def close(self) -> None:
        self.engine.dispose()
```

### 9.2 Keep the RAG facade small

The TUI talks only to `RagBackend`. This class connects the document and chat features and exposes the existing interface. Keep `shell.py` for UI-only mode. Replace `convo/chat/service.py`:

```python
from pathlib import Path

from convo.auth.chatgpt import ChatGPTAuth
from convo.auth.credentials import KeyringCredentialStore
from convo.core.config import Settings
from convo.core.contracts import Answer, Document, Message
from convo.providers.openai import ChatGPTProvider
from convo.rag.index import DocumentIndex


class RagBackend:
    def __init__(self, settings: Settings):
        self.documents = DocumentIndex(settings)
        self.auth = ChatGPTAuth(KeyringCredentialStore())
        self.chat = ChatGPTProvider(self.auth)

    async def prepare(self, path: Path) -> Document:
        return await self.documents.prepare(path)

    async def answer(
        self, document: Document, question: str, history: tuple[Message, ...]
    ) -> Answer:
        hits = await self.documents.search(document, question)
        return await self.chat.answer(document.path.name, question, history, hits)

    async def login_openai(self) -> str:
        return await self.auth.login()

    def close(self) -> None:
        self.documents.close()
```

`DocumentIndex` owns indexing/search and closes each database session before returning. The RAG facade sends retrieved hits and local history to the chat client. Authentication stays behind `ChatGPTAuth`.

`prepare()` returns only after its transaction commits; rollback keeps incomplete data invisible. The UUID includes the content hash and recipe, so an old conversation references its own indexed snapshot even when the same path is reindexed. Old snapshots remain in PostgreSQL until you deliberately prune them; this baseline always re-embeds rather than claiming cache reuse.

The file is reopened by readers. The stat comparison catches normal edits during preparation, but is not a strong snapshot guarantee; use a bounded temporary copy if you need readers to consume exactly the bytes you hashed. A changed source after preparation is not watched: select it again to index the new version.

`asyncio.to_thread` keeps the TUI responsive; its underlying thread does not stop when the awaiting coroutine is cancelled. Keep indexing serialized and don't add cancel-and-restart behavior without a cancellation design.

**Checkpoint:** exercise `DocumentIndex.prepare()` and `DocumentIndex.search()`, then `RagBackend.answer()` and `login_openai()` outside the UI. Verify real PostgreSQL rows, document-isolated results, source labels, and token refresh. Fix failures there before wiring the UI.

## 10. Connect to the TUI

`core/contracts.py` defines the `Backend` methods plus `AccountControls` for `/login`. Implement those methods on `RagBackend`. `ShellBackend` stays UI-only and intentionally does not advertise account controls, so the TUI explains that login is pending.

Change the imports in `convo/__main__.py`:

```python
from convo.core.config import load_settings
from convo.chat.service import RagBackend
```

Remove the ShellBackend import, then replace the current construction inside `main()`:

```python
settings = load_settings()
backend = RagBackend(settings)
try:
    ConvoApp(directory=directory, backend=backend).run()
finally:
    backend.close()
```

`chat/sessions.py` owns the active in-memory session and its completed history; the TUI owns presentation. It passes the current question once, with a tuple of prior completed turns. It already displays sources, preparing/thinking state, recoverable errors, and clears history on file changes. The backend never imports Textual.

Prewarm/download Qwen outside the TUI:

```sh
uv run --extra backend python -c 'from convo.rag.embeddings import Embedder; print(len(Embedder("Qwen/Qwen3-Embedding-0.6B").query("warm up")))'
uv run --extra backend convo
```

To browse files from any current directory after implementing the backend:

```sh
uv tool install --python 3.12 --editable '/Users/mohitsharma/Desktop/Projects/convo[backend]'
cd ~/Documents
convo
```

Your browsing directory selects files; your configured database and project `.env` stay independent of it.

**Checkpoint:** `/login` → ChatGPT account connected → `/file` → select → prepare → question → ChatGPT answer → sources. Database/network failure should restore an enabled input. The UI intentionally uses generic provider errors to avoid exposing credentials; reproduce backend calls separately for diagnosis.

## 11. Verify the full pipeline

```sh
uv run --extra backend ruff format --check .
uv run --extra backend ruff check .
uv run --extra backend ty check
uv run --extra backend pytest -q
uv run --extra backend alembic check
```

The existing tests check the shell with injected adapters. Add real backend checks as you implement it:

1. Known facts: retrieval finds them and answers cite the actual evidence.
2. Conflicting documents: filtering prevents facts from one appearing in the other.
3. Empty, malformed, unreadable and oversized files: no partial committed index.
4. Reindexing the same snapshot: no duplicate chunk ordinals; changed bytes get a new ID.
5. Failed writes: transaction rollback leaves the previous snapshot usable.
6. Bad credentials, missing vector extension and timeouts: understandable errors without leaked secrets.
7. Text PDF/DOCX: real page labels or honest reader-section labels; scanned PDFs fail without pretending OCR happened.

PostgreSQL stores plaintext excerpts alongside vectors. The ChatGPT adapter receives the question, bounded local history and retrieved excerpts; Qwen embeddings run locally. `/clear` and `/reset` affect the UI session, not stored snapshots. Only prune database rows when you intend to delete the index.

Build the baseline first. Then improve query rewriting, snapshot reuse, source precision, live streaming, and eventually HNSW/reranking after measuring retrieval quality.
