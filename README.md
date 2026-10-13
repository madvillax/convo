# convo

A minimal Python TUI for chatting with a file: black background, muted text, rectangular input, and a searchable `/file` picker.

**The interface works. You implement the RAG backend.** The default shell selects paths and shows a backend-pending message; it does not parse, embed, upload, query PostgreSQL, or call Hermes.

## Run the shell

Python 3.11+ is required; Python 3.12 is recommended. Use [uv](https://docs.astral.sh/uv/):

```sh
uv sync --python 3.12
uv run convo
```

Install an editable command to launch from any directory:

```sh
uv tool install --python 3.12 --editable /Users/mohitsharma/Desktop/Projects/convo
cd ~/Documents
convo
```

`convo` browses the directory you launched it from. You can also use `convo --directory ~/Documents`.

## Use

1. Enter `/file`, then filter by filename.
2. Use ↑/↓ and Enter to select a file or open a folder; Esc closes the picker.
3. Ask a question. Hermes answers become available after you implement and connect the backend.

| Command | Action |
| --- | --- |
| `/file` or Ctrl+O | Pick another file |
| `/help` | Show commands |
| `/clear` | Clear conversation, keep file |
| `/reset` | Clear conversation and detach file |
| `/quit` or Ctrl+C | Exit |

The picker offers `.txt`, `.md`, `.pdf`, `.docx`, `.csv`, `.json`, `.py`, `.rst`, and `.log`. It omits hidden entries and symbolic links. Input is single-line; the transcript scrolls vertically. A terminal of at least 50 columns × 18 rows works best.

## Build your backend

Follow [backend.md](backend.md) in order:

**PostgreSQL → SQLAlchemy models → Alembic migrations → LlamaIndex readers/chunkers → Qwen3 embeddings → pgvector retrieval → Hermes → TUI connection.**

The package lives directly in `convo/`. The backend separates configuration, domain contracts, database/session/models, repositories, ingestion, providers, and services. These files are scaffolds with clear responsibilities, ready for you to fill in. `migrations/env.py` deliberately stops until you complete the Alembic setup in the guide.

The contract is `convo/backend/domain/contracts.py`. Implement the two methods in `convo/backend/services/rag.py`, then switch the entry point from ShellBackend to RagBackend. Keep `services/shell.py` for UI-only mode and tests.

LlamaIndex is used **only for file readers and chunkers**. Your code owns indexing, SQLAlchemy transactions, pgvector queries, prompts, generation and history handling.

Backend dependencies are declared in an optional extra:

```sh
uv sync --extra backend
```

This includes PyTorch and parser libraries. Qwen weights download only when you load the embedding model. No PostgreSQL instance or model weights have been created by the scaffold.

## Format, lint, type-check, test

Ruff and ty are dev dependencies managed by uv:

```sh
uv run ruff format .
uv run ruff check .
uv run ty check
uv run pytest -q
```

After implementing imports of optional backend packages, use `uv run --extra backend ty check` and `uv run --extra backend pytest -q`.

The existing tests check the TUI with injected adapters: filtering, selection, folder navigation, cancellation, pending-backend messaging, sources, history isolation, error recovery and a small terminal. They do not validate a live database or model inference.
