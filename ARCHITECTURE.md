# Convo backend: architecture and implementation guide

Convo is a Python/Textual app for conversations about a selected file. PostgreSQL stores both the indexed document snapshots and durable conversations. Qwen3 provides local embeddings; PostgreSQL full-text search adds keyword retrieval; a local cross-encoder reranks passages; the connected ChatGPT account generates schema-constrained answers with supporting quotes.

The implementation lives directly in `convo/`. There is no HTTP server to start. The TUI calls the backend through Python contracts.

## 1. Understand the folders

```text
convo/
├── pyproject.toml
├── uv.lock
├── .env.example
├── alembic.ini
├── migrations/
│   ├── env.py
│   └── versions/
├── convo/
│   ├── __init__.py
│   ├── __main__.py
│   ├── core/
│   │   ├── config.py          # environment settings and retrieval tuning
│   │   ├── contracts.py       # messages, answers, sessions and backend protocols
│   │   └── exceptions.py      # recoverable user-facing backend errors
│   ├── ui/
│   │   ├── app.py             # transcript and asynchronous command handlers
│   │   ├── commands.py        # slash-command registry and suggestions
│   │   ├── files.py           # file picker
│   │   ├── models.py          # account model picker
│   │   ├── sessions.py        # saved conversation picker
│   │   ├── preview.py         # --shell adapter
│   │   └── theme.tcss
│   ├── llm/
│   │   ├── auth.py            # browser OAuth and token refresh
│   │   ├── credentials.py     # OS keyring and private account preferences
│   │   ├── client.py          # account models and grounded-answer generation
│   │   ├── models.py          # catalog and reasoning capability normalization
│   │   └── streaming.py       # streamed Responses requests and JSON text collection
│   ├── pipeline/
│   │   ├── chat.py            # one message: route → retrieve → answer → save
│   │   ├── routing.py         # pure greetings, overview detection, follow-up queries
│   │   ├── sessions.py        # active TUI view of a saved conversation
│   │   ├── ingestion.py       # selected-file readers and extraction limits
│   │   ├── chunking.py        # LlamaIndex SentenceSplitter
│   │   ├── embeddings.py      # cached Qwen3 model and dimension checks
│   │   ├── reranking.py       # local cross-encoder and weak-match filtering
│   │   ├── index.py           # preparation and document-scoped retrieval
│   │   └── worker.py          # reusable child process, progress and cancellation
│   ├── prompts/
│   │   ├── answers.py         # versioned instructions and bounded context builder
│   │   └── schema.py          # Pydantic schema, citation checks and rendering
│   └── db/
│       ├── base.py            # shared SQLAlchemy metadata
│       ├── models.py          # four mapped tables
│       ├── session.py         # engine/session factory
│       ├── documents.py       # document snapshot writes
│       ├── chunks.py          # chunk writes, hybrid search and rank fusion
│       └── conversations.py   # durable sessions and atomic completed turns
└── tests/
    ├── test_answers.py
    ├── test_backend.py
    ├── test_database.py
    ├── test_generation.py
    ├── test_preparation.py
    ├── test_retrieval.py
    └── test_ui.py
```

Empty `__init__.py` files mark packages and are omitted from the inner tree for readability. `llm/` keeps the account connection and provider code together. `pipeline/` contains the application flow and retrieval work. Database query files live beside the models, avoiding a second repositories subdirectory. Prompt content and output validation have their own small folder.

The main abstractions are `Backend` for the UI, optional account/model/session controls, `RagBackend` for orchestration, `IndexWorker` for isolated document work, and `Conversations` for saved chat data. There are no domain/repository-interface/unit-of-work packages or agent framework.

**Checkpoint:** follow one request from `ui/app.py` to `pipeline/chat.py`; it delegates to the worker, provider, and conversation store.

## 2. Install with uv and create local PostgreSQL storage

```sh
uv sync --python 3.12 --extra backend
uv run --extra backend convo --setup
uv run --extra backend convo
```

`convo --setup` is the supported first-run path for an installed CLI as well. It detects Docker or Podman, starts/initializes a Podman machine on macOS when needed, creates a named `convo-postgres-data` volume, and binds the `convo-postgres` pgvector container only to `127.0.0.1:5432`. It generates a database password and writes the connection string with mode `0600` to `~/.config/convo/.env` (or `$XDG_CONFIG_HOME/convo/.env`). It never deletes, replaces, or resets an existing container or volume.

For a development-only manual setup, create the project's database container once:

```sh
podman run --name convo-postgres \
  -e POSTGRES_USER=convo \
  -e POSTGRES_PASSWORD=convo \
  -e POSTGRES_DB=convo \
  -p 127.0.0.1:5432:5432 \
  -v convo-postgres-data:/var/lib/postgresql/data \
  -d pgvector/pgvector:pg16
```

For later runs, use `podman start convo-postgres`. The named volume preserves the database across container stops. The example credentials are for local development; set your own values consistently if changed. An installed CLI should use `convo --setup` instead, so it can keep a random password in its private user settings file.

Configure the project `.env` from `.env.example`:

```dotenv
DATABASE_URL=postgresql+psycopg://convo:convo@localhost:5432/convo
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L6-v2
RERANK_MIN_SCORE=-3
RETRIEVAL_CANDIDATES=20
```

`core/config.py` loads the checkout's `.env` independently of the file browsing directory. Environment variables take priority. Use `postgresql+psycopg://` for the synchronous Psycopg driver. OAuth tokens belong in the OS keyring, never `.env`.

```sh
podman exec convo-postgres pg_isready -U convo -d convo
uv run --extra backend alembic upgrade head
uv run --extra backend alembic check
```

Migration `a42e9d8f0b31` adds the generated full-text column, a GIN index, and conversation tables. Existing text automatically populates the generated column, so existing vector snapshots do not need re-embedding for hybrid retrieval. It follows the existing revisions and preserves document/chunk rows. Its downgrade removes the added conversation/search schema; do not downgrade if you need saved chats.

**Checkpoint:** the container is ready, migrations reach head, and `alembic check` reports no schema drift. If Podman itself cannot start, repair the VM/container before using database-dependent commands. The TUI still opens and reports storage failures without loading ML models first.

## 3. Understand the schema and SQLAlchemy sessions

| Table | Stored data |
| --- | --- |
| `documents` | Snapshot UUID, source path, content hash and embedding/chunking recipe |
| `chunks` | Document FK, ordinal, text, reader locator, `VECTOR(1024)` and generated `TSVECTOR` |
| `chat_sessions` | Conversation UUID, optional document snapshot FK, title and timestamps |
| `messages` | Session FK, ordinal, role, rendered content, cited sources and structured JSON |

A document can have many chunks and conversations. A conversation has ordered messages. `(document_id, ordinal)` and `(session_id, ordinal)` are unique. Message deletion cascades from a conversation; a referenced document snapshot is protected by its session FK. This keeps an old conversation tied to its own indexed content.

`db/base.py` defines one declarative `Base` with shared metadata and predictable constraint names. SQLAlchemy models register their tables there. `migrations/env.py` imports those mappings and supplies `Base.metadata` to Alembic. Models describe the desired schema; Alembic revisions apply changes. The application does not call `create_all()` at startup.

`db/session.py` creates an engine and `sessionmaker`. Each operation gets a short-lived SQLAlchemy session/transaction. Connections use a 10-second connect timeout. Conversation storage is initialized lazily; opening the TUI does not connect to PostgreSQL.

These names describe different things:

- **SQLAlchemy Session:** one unit of database work, with commit/rollback and connection management.
- **Chat session:** a durable conversation row and ordered messages in PostgreSQL.
- **`pipeline/sessions.py::ChatSession`:** the active conversation view used by the TUI, restored from storage.

**Checkpoint:** inspect the four tables, then trace `Conversations.create()`, `load()`, and `append_turn()` in `db/conversations.py`.

## 4. Prepare a selected file

`pipeline/index.py::DocumentIndex._prepare()`:

1. Checks PostgreSQL and the migrated chunks schema before parsing/downloading.
2. Reads at most 10 MB and hashes the selected file's bytes.
3. Parses a temporary copy of exactly those bytes.
4. Loads Qwen, splits the text, and creates normalized embeddings.
5. Rechecks the source file to reject changes during indexing.
6. Writes the document and chunks in one transaction.

Supported extensions are `.txt`, `.md`, `.pdf`, `.docx`, `.csv`, `.json`, `.py`, `.rst`, and `.log`. Readers only receive the selected file. There is a 500,000-character extracted-text limit, a 50 MB DOCX expanded-archive limit, and a 2,000-chunk limit.

LlamaIndex is used only for `SimpleDirectoryReader`, file readers, and `SentenceSplitter`. PDF pages retain their real page label. Other reader sections have coarse section locators, which must not be presented as exact line numbers or Word pages.

Chunks use Qwen's tokenizer with 512-token windows and 64-token overlap. `Qwen/Qwen3-Embedding-0.6B` returns 1,024-dimensional vectors; questions use its `query` prompt and normalization. The model's maximum sequence length is bounded. The embedding recipe is part of snapshot identity, preventing incompatible vectors from being silently reused.

The loader first tries cached assets without Hub network checks, then fetches missing files if the cache is incomplete. Successful model loads remain in memory in the child process.

**Checkpoint:** prepare a small Markdown file and verify its document/chunk rows. Changing file content creates a different snapshot. Selecting an unchanged file may re-embed it, but keeps deterministic snapshot identity.

## 5. Retrieve with hybrid search and reranking

For a specific question, `db/chunks.py::retrieve()` does both searches against the selected snapshot:

1. **Dense search:** Qwen question vector → pgvector cosine distance → closest candidates.
2. **Keyword search:** question content terms (up to 32, joined with OR) → PostgreSQL `websearch_to_tsquery('english', keyword_query)` → generated `search_vector` → `ts_rank_cd` ordering.
3. **Reciprocal rank fusion:** each candidate receives `1 / (60 + rank)` from each result list; duplicate chunk IDs merge. The strongest merged candidates form a bounded pool.
4. **Cross-encoder reranking:** `pipeline/reranking.py` scores each question/passage pair, sorts the pool, filters weak matches, and returns up to five passages.

Both SQL branches constrain `document_id`. Keyword/full-text ranking is PostgreSQL's ranking function, not BM25. Vector and keyword raw scores are not added directly because their scales differ.

The reranker defaults to [`cross-encoder/ms-marco-MiniLM-L6-v2`](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2), loaded with sentence-transformers and a 512-token input limit. It is a separate, small local model; Qwen remains the embedding model. `RETRIEVAL_CANDIDATES` sets each branch/pool bound (default 20, allowed 5–50). `RERANK_MIN_SCORE` is a raw ranking-logit cutoff (default -3), not a confidence probability. Tune it with representative relevant and unrelated questions; model changes require retuning. The default text-search configuration and reranker are oriented toward English; evaluate and choose an appropriate reranker before relying on other languages.

Broad overview requests, such as “summarize this file”, need coverage instead of QA passage relevance. They sample up to five positions across the ordered chunks and rerank their presentation without the specific-question cutoff. The answer prompt describes the supplied excerpts; this is a bounded overview, not an exhaustive map/reduce summary of every chunk.

Short follow-ups can append the previous user question to the search query. The original current question and bounded history still go to generation. Pure greetings/thanks return a short local response without retrieval or an LLM call. A greeting mixed with a file question remains a document query. This routing uses conservative rules; there is no model tool-calling loop.

**Checkpoint:** test a paraphrase, an exact identifier, a question from another file, an unrelated question, a short follow-up, and a file overview. Check the evidence itself, not just fluent answer text.

## 6. Build the prompt context

`prompts/answers.py` contains the code-managed prompt version and context builder. It applies:

- A clear role, direct-answer style, and instructions to retain identifiers, units and conditions.
- Evidence-only factual claims, explicit handling of missing/conflicting information, and protection against instructions inside document text.
- Few-shot examples of a grounded answer and an insufficient-evidence answer.
- JSON-escaped evidence boundaries and application-assigned source IDs.
- A recent-history budget: up to 12 messages, 2,000 characters per message, 10,000 total.
- An evidence budget: up to five excerpts, 2,500 characters per excerpt, 10,000 total.

History helps interpret follow-ups; prior assistant answers are not factual evidence. Source IDs restart for every request. Only the current evidence may support citations. The prompt does not request hidden chain-of-thought text.

These are explicit prompt/context engineering measures. They improve the conditions for answering correctly; they do not guarantee semantic correctness.

**Checkpoint:** inspect the actual `make_input()` result using a local test fixture. Evidence containing quotes, JSON delimiters or “ignore these instructions” remains a string value inside the context payload.

## 7. Request a structured answer and validate citations

`prompts/schema.py` defines strict Pydantic models. The model response shape is:

```json
{
  "status": "answered",
  "sections": [
    {
      "text": "Backups run nightly at 02:00 UTC.",
      "citations": [
        {"source_id": 1, "quote": "Backups run nightly at 02:00 UTC."}
      ]
    }
  ]
}
```

`llm/streaming.py` sends this as a strict Responses API `text.format` JSON schema. It retains the ChatGPT-plan requirements: `store=false`, `stream=true`, instructions outside the user context, and explicit history in `input`. It omits `previous_response_id` and other unsupported stateful fields. The selected model and optional reasoning effort are preserved.

The transport collects text until `response.completed`. Failed, incomplete, refused, or interrupted streams cannot become saved answers. JSON is validated before the UI renders it; the UI does not display partially validated JSON tokens.

`parse_answer()` additionally checks:

1. The object fits the schema; extra fields and invalid types fail.
2. Every answered section has text and at least one citation.
3. Each source ID belongs to the current evidence.
4. Every supporting quote is 8–600 characters and occurs verbatim in that source, allowing whitespace differences only.
5. The model has not inserted its own numeric citation markers into answer text.

Python assigns the displayed `[1]`, `[2]`, etc., and maps only used citations to trusted filename/locator metadata. The sources section displays supporting quotes, not all retrieved chunks. The structured object is retained with the assistant message, with citation IDs normalized to the same numbering as the rendered answer and saved sources.

An invalid answer gets one correction attempt. A second failure produces a recoverable error without saving an incomplete turn. A selected model that rejects the structured request reports an actionable `/models` error; the app does not silently accept unstructured prose. Empty retrieval returns a local `insufficient_evidence` result without calling ChatGPT. Model-declared insufficient evidence is normalized to a brief local response.

Structure, valid IDs, and exact quotes can be checked mechanically. A quote can still be misinterpreted or fail to support an entire generated claim; there is no separate entailment verifier or guarantee of hallucination-free answers.

References: [official Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering), and [ChatGPT connection requirements](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

**Checkpoint:** exercise invalid IDs, paraphrased quotes, missing citations, malformed JSON, an insufficient-evidence response, and a successful response whose unused retrieved chunks are omitted from sources.

## 8. Save and resume conversations

`pipeline/chat.py::RagBackend.answer_session()`:

1. Loads the selected session's document snapshot and history from PostgreSQL.
2. Routes the message and runs retrieval/generation when needed.
3. Saves the user and assistant messages together in one transaction.
4. Returns the validated answer after that transaction commits.

No database transaction remains open during an embedding or ChatGPT call. A session-row lock and expected message count reject concurrent stale appends; they do not silently interleave answers based on old history. Failures roll back, and failed user requests do not enter history. Timestamps, ordered content, cited sources, and structured assistant output survive app restarts.

`/sessions` searches stored titles, filenames and IDs. Selecting a row restores its transcript, source quotes, and associated indexed snapshot. It does not need to reread or re-embed the original file. A resumed question searches the saved snapshot, even if the original path has changed. Use `/file` to create a conversation about a newly indexed version.

`/new` creates a saved empty conversation with the current file. `/clear` aliases that behavior. `/reset` creates one without a file. They preserve older conversations. Selecting another file also creates a new session after preparation succeeds. Startup opens an empty view without storage/network work; use `/sessions` to resume.

`pipeline/sessions.py` only holds the active UI view. PostgreSQL is the durable source of truth. There is no automatic long-term history summarization; generation uses the bounded recent-history window while the complete transcript remains stored.

**Checkpoint:** complete a turn, exit, reopen with `/sessions`, and continue. Start `/new` and confirm the old conversation remains available. Retry a failed generation and confirm it did not add a partial turn.

## 9. Keep the TUI responsive

`pipeline/worker.py::IndexWorker` starts one child process only when file work is needed. It uses the same Python interpreter as the running CLI. A local pipe carries requests, stage messages and typed results. The current launcher uses macOS/Linux `pass_fds`.

ML imports, model loading, downloads and native stdout/stderr stay in that child. Output is captured from process creation in owner-only `~/.cache/convo/rag-worker.log`, respecting `XDG_CACHE_HOME`. The app does not globally redirect Textual's own output. The worker retains loaded models across successful operations.

File preparation displays filename, current stage, elapsed seconds and Esc cancellation. Cancellation terminates the process rather than abandoning an embedding thread. Uncommitted database writes roll back when the connection closes. A retry starts a fresh worker. Preparation has a 15-minute deadline; search/reranking has a 120-second deadline. First-time model downloads still take time.

```sh
# Optional warmup, outside the fullscreen interface:
uv run --extra backend convo --download-model
uv run --extra backend convo
```

The app restores saved account/model preferences from local metadata without a startup network refresh. `/models`, login and ordinary generation refresh the account catalog when needed. Tokens remain in the OS keyring; account metadata/preferences retain owner-only permissions. The ChatGPT account connection remains separate from database chat sessions.

**Checkpoint:** start offline, open `/`, cancel file preparation, recover from a database error, resize to 50×18, and cancel a session picker without changing the active conversation.

## 10. Verify implementation

```sh
uv run --extra backend ruff format --check .
uv run --extra backend ruff check .
uv run --extra backend ty check
uv run --extra backend pytest -q
```

The standard suite uses fakes for external services and skips database/model integration tests unless enabled. To test against a running Podman PostgreSQL instance, set an admin connection in `CONVO_TEST_DATABASE_URL`; the fixture creates and drops its own randomly named database. It never migrates or clears the application database:

```sh
CONVO_TEST_DATABASE_URL='postgresql+psycopg://convo:convo@localhost:5432/convo' \
CONVO_TEST_MODELS=1 uv run --extra backend pytest -q
```

The database role must be able to create databases, and pgvector must be installed on that PostgreSQL server. `CONVO_TEST_MODELS=1` loads/downloads the real Qwen and reranker models. Without it, database/schema/persistence checks still run and the model-heavy checks skip.

For development machines that already have PostgreSQL `initdb`, `pg_ctl` and pgvector installed, an alternative test-only fixture creates and removes a temporary cluster:

```sh
CONVO_TEST_POSTGRES=1 CONVO_TEST_MODELS=1 uv run --extra backend pytest -q
```

Coverage includes preserving/backfilling old snapshots through the new migration, no Alembic schema drift, true full-text/vector fusion, document isolation, overview coverage, real local models, quote validation, corrective retry, wire-level JSON schema serialization, saved-session restarts, atomic failure handling, stale-session protection, worker cancellation/output isolation, and Textual keyboard/picker behavior. Live ChatGPT account authorization and generation are separate from mocked transport verification.

For a change to retrieval quality, keep a small set of representative questions with expected source passages. Tune candidate count/cutoff against those examples. Passing type checks and unit tests does not measure answer quality on every document.
