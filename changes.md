# Convo implementation changes

Latest milestone: hybrid retrieval/reranking, structured grounded answers, durable conversations, and a simpler six-folder package. See the final section below and the current [backend guide](backend.md). Earlier sections record historical paths and verification at their respective milestones.

## What changed

| Before | Now |
| --- | --- |
| Commands ran only after Enter; typing `/` showed no choices. | `/` immediately opens a command menu above the rectangular input. Typing filters the list. |
| The backend silently chose the first available ChatGPT model. | `/models` opens a searchable picker populated from the connected account's model catalog. |
| Shift+Tab moved focus away from the composer. | Shift+Tab in the main input cycles thinking levels and keeps the draft intact. Inside pickers it keeps normal focus behavior. |
| The footer displayed a generic ChatGPT label. | It displays the selected model and current thinking level. Thinking stays visible even when a long model name is shortened. |
| File-picker arrows first changed focus without moving the selection. | Each arrow press moves the highlighted entry immediately; typing can continue filtering. |
| A failed answer cleared the input. | The question is restored for retry, and failed turns stay out of history. |
| The globally installed command had only the interface dependencies. | The existing editable uv tool installation now includes the backend extra. |

## Using it

1. Type `/`. Use ↑/↓ to select a command, Tab to complete its name, Enter to run it, and Esc to dismiss the menu.
2. Run `/login`. Once authorization succeeds, Convo loads the account's available models.
3. Run `/models`. Filter by display name or model ID, then press Enter to select. Esc cancels without changing anything. `/models <model-id>` is also supported.
4. Press **Shift+Tab** while the main input has focus. It cycles `auto → known levels → auto`, for example `auto → low → medium → high → auto`.
5. Select a file with `/file` and ask questions. Subsequent requests use the selected model and thinking preference.

`auto` means the request omits `reasoning.effort` and uses the model's server default. A model without known adjustable reasoning levels stays on auto. Model/thinking preferences remain selected when clearing history, resetting the chat, or choosing another file.

## Approaches

### One command registry

`convo/ui/commands.py` holds command names and descriptions. The slash menu, prefix matching, Tab completion, and `/help` use that registry. The input keeps keyboard focus while arrows operate the menu, so users can continue typing a filter without switching widgets.

Priority key bindings are enabled only when the main composer has focus. They do not intercept arrows, Escape, or Shift+Tab inside file/model pickers. Each picker stops its input events from bubbling into the main command handler.

### Typed UI/backend controls

`convo/core/contracts.py` adds:

- `ChatModel`: model ID, display name, known reasoning levels, and optional default.
- `GenerationSelection`: current model, reasoning preference, and connected state.
- `GenerationControls`: listing models, selecting one, cycling thinking, and reading the current selection.

The TUI uses this protocol. `RagBackend` delegates these operations to `ChatGPTProvider`. Textual does not make HTTP requests, access credentials, or decide model capabilities.

### Account-scoped model discovery

`ChatGPTProvider` fetches `GET https://api.openai.com/v1/models` with the connected account's OAuth token. It keeps displayable entries (`visibility == "list"`), preserves server order, displays `display_name`, and uses the selected `slug` for inference.

The provider caches the catalog for five minutes during ordinary use. `/models` refreshes it explicitly; login invalidates the previous cache; startup restores a saved account connection locally. Catalog refresh happens on demand (see the preparation/startup fixes below). A removed model falls back to the first available entry, with any incompatible thinking preference reset to auto. Selecting an invalid model ID fails without replacing the current selection.

This follows the [official account model-list and inference flow](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference).

### Model-aware thinking levels

`convo/providers/models.py` normalizes optional reasoning capability metadata when a catalog includes it. It accepts recognized effort names, removes duplicates, and filters unknown values. The public SIWC example only promises the model ID/display name; capability fields are optional.

When capability metadata is absent, Convo offers the conservative `low`, `medium`, and `high` subset for these documented standard model IDs: `gpt-5.5`, `gpt-5.6`, `gpt-6-astra`, `gpt-6-sol`, `gpt-6.1-sol`, and `gpt-6-luna` (including their dated snapshots). Unfamiliar models remain on auto. It does not assume every model supports every reasoning value or a separate pro model's settings.

The selected effort is passed into `complete_chatgpt()` and then into the Responses API as `reasoning={"effort": ...}`. Auto is omitted from the wire payload. Requests retain `store=false` and `stream=true`.

References: [reasoning effort](https://developers.openai.com/api/docs/guides/reasoning), [ChatGPT-plan API limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

### Preferences and credentials

The existing per-user account profile now stores `selected_model`, `selected_model_name`, and `selected_reasoning_effort`. Old profiles without these fields remain readable. Preference writes replace only those fields; token refresh preserves them. OAuth tokens remain in the OS keyring.

The UI restores saved selections locally; catalog refresh happens on demand. A catalog/network failure restores an enabled composer, preserves drafts, and displays a recoverable error without exposing raw provider exceptions. A connected account whose catalog is unavailable is shown as needing a model rather than being shown as signed out.

### Layout and picker repairs

The model/thinking footer uses a flexible model label and a separate thinking label. Compact terminal rules reduce spacing, hide the directory heading, and constrain the command menu so the input and settings stay on screen. An open menu adjusts when the terminal is resized.

The model picker uses the same muted, rectangular style as the file picker. Filtering, an empty result, cancellation, selection, and arrow keys are handled explicitly.

### Installed CLI environment

The installed executable at `~/.local/bin/convo` already pointed to this checkout, but its separate uv tool environment lacked SQLAlchemy, Psycopg, OpenAI, dotenv, and sentence-transformers. Updating the project with `uv sync` did not fix that environment.

It was reinstalled with:

```sh
uv tool install --python 3.12 --force --editable '/Users/mohitsharma/Desktop/Projects/convo[backend]'
```

The startup dependency error and README now distinguish the project command (`uv run --extra backend convo`) from the installed tool. UI-only preview remains available with `convo --shell`.

## Main files

| File | Responsibility |
| --- | --- |
| `convo/ui/app.py` | Command interactions, model workers, thinking shortcut, displayed state, and error recovery |
| `convo/ui/commands.py` | Command registry, prefix matching, and menu widget |
| `convo/ui/models.py` | Searchable account model picker |
| `convo/ui/files.py` | Immediate arrow navigation and event isolation |
| `convo/ui/theme.tcss` | Menu, pickers, settings footer, and compact layout |
| `convo/core/contracts.py` | Model/selection values and UI-facing controls |
| `convo/providers/models.py` | Catalog parsing and reasoning capability policy |
| `convo/providers/openai.py` | Account catalog cache, selection, and generation preferences |
| `convo/auth/credentials.py` | Backward-compatible persisted preferences |
| `convo/auth/chatgpt.py` | Preference writes and preservation through OAuth refresh |
| `convo/chat/service.py` | Backend delegation for the UI controls |
| `convo/chat/streaming.py` | Serialize the selected reasoning effort for inference |
| `convo/__main__.py` | Actionable project-versus-installed-tool startup errors |
| `tests/test_ui.py` | Real Textual keyboard, picker, focus, sizing, and recovery tests |
| `tests/test_generation.py` | Catalog normalization, persisted choices, token refresh, and SDK HTTP payload tests |

The database schema and RAG retrieval algorithm are unchanged by these controls. Conversation history remains process-local; the selected model/thinking settings survive restart independently of it.

## Verification

```sh
uv run --extra backend ruff format --check .
uv run --extra backend ruff check .
uv run --extra backend ty check
uv run --extra backend pytest -q
```

At the earlier controls milestone, 24 tests passed covering slash-menu keyboard selection/completion, account model selection, thinking changes, draft preservation, startup restoration, cancellation, empty filters, small-terminal layout and resizing, file navigation, refresh failures, preference persistence, and the actual OpenAI SDK request body through mocked HTTP transport.

Textual screenshots were rendered and inspected at 100×32 and 50×18, including the command menu and model picker. Account authorization, the live model catalog, generation, and PostgreSQL connectivity still require a real-service run; the automated tests use local fakes and mocked HTTP responses.

The installed executable was also smoke-tested in a real PTY: typing `/` displayed the command menu, and Ctrl+C exited cleanly. Its repaired tool environment successfully imported and constructed the real backend, then disposed the engine without opening a database connection.


## File preparation and startup fixes — 2026-10-15

### Cause

The backend imported sentence-transformers/Torch and LlamaIndex before Textual could draw. Startup also disabled the composer while refreshing the account catalog. Selecting a file then loaded/downloaded Qwen inside a thread in the same process; third-party HTTP logs and native download output wrote directly over the TUI. Preparation had no stage information or cancellation, and storage was checked only after parsing/embedding.

A live check also found an incomplete Qwen cache: model weights existed but supporting pooling/tokenizer assets were missing. Sentence-transformers can raise `TypeError` for a missing local pooling configuration rather than the usual `OSError`.

### Approach and behavior

- `rag/worker.py` owns one reusable child process, started only when a document operation is requested. The process uses the current Python environment, so both `uv run` and the editable installed CLI use their own dependencies correctly. Heavy ML/parser imports happen there. The launcher uses a local pipe and macOS/Linux `pass_fds`; there is no server to run.
- Worker stdout/stderr are captured from process creation, including native writes and descendant resource-tracker warnings. Diagnostics go to `~/.cache/convo/rag-worker.log` (or `$XDG_CACHE_HOME/convo/rag-worker.log`) with permissions `0600`. No terminal output redirection is applied globally to Textual.
- Preparation now shows the chosen filename, stage, elapsed seconds, and Esc cancellation. Stages cover PostgreSQL checks, reading, Qwen loading/download, chunking, embedding, and saving. The footer keeps the cancel shortcut visible at narrow widths.
- Esc terminates the child and restores the composer. It does not leave an uncancellable embedding thread behind. The previous document/history remains active until another file finishes successfully. Retry creates a fresh process; successful operations reuse the loaded model. Uncommitted database work rolls back on disconnect; a transaction already committed is retained.
- PostgreSQL connectivity and the chunks table are checked before parsing/model work. Connection errors explain starting Podman; schema errors explain applying Alembic migrations. Unexpected errors show the diagnostic-log location, while raw exceptions stay out of the TUI.
- Operations are bounded: preparation has a 15-minute limit, retrieval 120 seconds, and database connection attempts 10 seconds. A failure/cancellation restores usable input rather than leaving “preparing file…” forever.
- Qwen first tries cached assets without Hub checks. An incomplete cache falls back to fetching missing assets; successful loads remain in memory in the child process. `convo --download-model` is an optional explicit download/warmup command outside the fullscreen UI. First-time weight download and loading still take time; they are now visible and cancellable.
- Startup restores saved account/model settings locally. It does not load embeddings, connect to PostgreSQL, or fetch the account model catalog. `/models`, login, and generation refresh the catalog when required.

Main files: `convo/rag/worker.py`, `convo/rag/index.py`, `convo/rag/embeddings.py`, `convo/rag/ingestion.py`, `convo/rag/chunking.py`, `convo/chat/service.py`, `convo/core/contracts.py`, `convo/ui/app.py`, `convo/__main__.py`. README and backend guide now describe the process boundary and setup command.

### Verification

- Backend import timing on this machine fell from **5.60s to 0.48s**. This measures the import, not file indexing; terminal drawing is measured separately.
- Real Podman PostgreSQL was available and `alembic check` reported no pending schema changes.
- A real Qwen/PostgreSQL test prepared a small Markdown file, retrieved the expected fact with pgvector, and reindexed it successfully. The initial cache-repair run took **20.83s**; with assets cached, a new process took **7.67s**. The installed CLI's separate uv environment also succeeded in **7.55s**. The combined retrieval plus reindex interval within the same process was under **0.5s**.
- Automated coverage adds subprocess stdout/stderr isolation, stage reporting, process reuse, cancellation, timeout/crash recovery, lazy startup imports, database checks before model loading, partial-cache repair, and real Textual progress/cancel/error/retry behavior.

Final checks passed:

```sh
uv run --extra backend ruff format --check .  # 49 files formatted
uv run --extra backend ruff check .          # passed
uv run --extra backend ty check              # passed
uv run --extra backend pytest -q             # 34 passed
uv run --extra backend alembic check         # no schema drift
```

The installed `convo` command was measured in a real PTY across three runs: first draw took **0.54s, 0.34s, and 0.35s**. Typing `/` displayed the command menu, and `/quit` exited cleanly each time. A real Textual run with the actual backend also cancelled Qwen loading, restored the composer, retried successfully, and displayed the ready document. Preparation/ready screenshots were rendered and visually inspected. Temporary smoke-test rows were removed afterward.

These preparation checks do not assert a new live ChatGPT authorization or generation run. Restart the existing editable CLI with `convo` to use these fixes; no reinstall is needed for the current installation.


## Hybrid retrieval, grounded answers, persistent sessions and simpler folders — 2026-10-15

### Architecture

The Python package now has six responsibility-based folders:

```text
convo/
├── core/       settings, value objects and backend protocols
├── ui/         Textual and command/file/model/session interactions
├── llm/        ChatGPT OAuth, credentials, catalog and transport
├── pipeline/   chat orchestration, routing, ingestion, retrieval and worker
├── prompts/    instructions, bounded context and structured-answer validation
└── db/         SQLAlchemy mappings, connections and queries
```

Auth and provider code moved into `llm/`; chat and RAG modules moved into `pipeline/`; database queries moved directly into `db/`. The unused provider base and tiny standalone history helper were removed. The active-session view remains one dataclass; `RagBackend` coordinates the flow. There are no added domain/repository-interface/agent-framework layers. Imports, the subprocess entry point, tests, README and backend guide were updated together. The package remains directly `convo/`, without a `src/` prefix.

### Hybrid retrieval and reranking

`db/chunks.py` now runs document-scoped pgvector cosine search and PostgreSQL full-text search. Natural-language questions become up to 32 content terms joined with OR, so question scaffolding and missing one word do not eliminate every keyword result. The generated English `TSVECTOR` column has a GIN index. PostgreSQL `ts_rank_cd` ranks keyword matches; this is full-text ranking, not BM25.

Reciprocal rank fusion merges the two rankings using `1 / (60 + rank)` and deduplicates chunk IDs. The merged pool is reranked by the local `cross-encoder/ms-marco-MiniLM-L6-v2`; Qwen3 remains the embedding model. The default pool is 20 and up to five evidence passages survive reranking. A raw-logit cutoff (-3 by default) rejects weak matches; it is configurable and is not a calibrated probability. Default keyword/reranker behavior is oriented toward English.

Direct QA relevance scores are inappropriate for whole-file summary requests. Explicit overview requests sample sections across the stored snapshot, rerank their order, and bypass the QA cutoff. The prompt describes the supplied excerpts rather than claiming exhaustive coverage. A real model check caught and verified this edge case.

`pipeline/routing.py` handles pure greetings/thanks locally, leaving mixed greetings and document questions on the retrieval path. Short follow-ups use the prior user question as additional search context. An empty evidence set returns an insufficient-evidence answer without an LLM call. This is application-owned routing; no tool-calling loop was introduced.

### Prompt and context engineering

`prompts/answers.py` owns the versioned prompt and context builder. It provides a specific role, concise answer style, preservation of code identifiers/numbers/conditions, handling for missing/conflicting evidence, few-shot examples, untrusted-document instructions, and explicit separation of history from evidence. Evidence is JSON-escaped to preserve source boundaries.

The context includes up to five bounded excerpts (2,500 characters each, 10,000 total) and the newest bounded history (up to 12 messages, 2,000 characters each, 10,000 total). History helps interpret references; it is not evidence for new claims. No hidden chain-of-thought output is requested.

### Structured grounded answers and citations

`prompts/schema.py` defines strict Pydantic models:

```json
{
  "status": "answered",
  "sections": [{
    "text": "Backups run nightly at 02:00 UTC.",
    "citations": [{"source_id": 1, "quote": "Backups run nightly at 02:00 UTC."}]
  }]
}
```

The Responses request uses strict `text.format` JSON schema while retaining ChatGPT-plan `stream=true`, `store=false`, explicit input history, and instructions. Stream failures, refusals and incomplete responses cannot become completed answers.

Application validation requires citations on every answered section, checks IDs against the current evidence, and checks that each 8–600-character quote occurs in that excerpt (whitespace differences allowed). Python renders the displayed citation numbers. Only cited quotes become sources, and persisted structured IDs are normalized to match the displayed sources. The UI renders the answer as Markdown after validation, preserving bracketed code indices and keeping citations outside closing code fences.

There is one corrective retry for invalid structured/citation output. A second failure restores a recoverable input state and saves no incomplete turn. Insufficient-evidence responses carry no citations. A model that cannot accept the structured request reports an actionable model-selection error; it does not silently fall back to unstructured text.

These checks prove schema/ID/span validity, not semantic entailment of every generated statement. There is no separate claim-verification model.

The implementation follows the [official Structured Outputs format](https://developers.openai.com/api/docs/guides/structured-outputs), [prompt guidance](https://developers.openai.com/api/docs/guides/prompt-engineering), and [ChatGPT connection requirements](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations). The reranker is described in its [publisher model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2).

### Persistent conversations and commands

New `chat_sessions` and `messages` tables store titles, document-snapshot associations, timestamps, ordered messages, rendered sources and structured assistant output. `db/conversations.py` owns the SQLAlchemy transactions. The store connects lazily, preserving startup responsiveness.

Successful user/assistant pairs commit together after generation/validation. Failures save neither half. A row lock plus expected message count rejects competing stale appends. The full stored transcript survives restart, while only bounded recent history enters the next model context.

- `/sessions` opens a searchable picker with title, filename, turn count and timestamp.
- `/sessions <uuid>` resumes a saved conversation directly.
- `/new` starts a saved conversation with the selected file.
- `/clear` aliases `/new`; `/reset` starts one without a file.
- Previous conversations remain available. File selection creates a new conversation after successful preparation.
- Resuming restores the original indexed snapshot and saved source quotes, even if the source file has moved or disappeared. It does not re-embed the original path.

The six-folder architecture, configuration, checkpoints and current implementation flow are documented in `backend.md`. `README.md` covers the normal commands and setup.

### Migration and configuration

Revision `a42e9d8f0b31` follows `5c3b75f9c5c1`. It adds the full-text column/index and chat tables while preserving existing documents/vectors. A migration check with seeded old rows verified preservation and generated full-text backfill. Alembic metadata matches the migrated schema.

New optional environment settings: `RERANKER_MODEL`, `RERANK_MIN_SCORE`, and `RETRIEVAL_CANDIDATES`. `convo --download-model` prepares both Qwen and the reranker outside the TUI. Both models otherwise load lazily in the existing isolated worker; progress/output isolation/cancellation remain in place.

Once the normal Podman database is running, apply the migration from the checkout:

```sh
uv sync --extra backend
uv run --extra backend alembic upgrade head
uv run --extra backend convo
```

### Verification and current local-service limitation

Ruff formatting/lint and ty passed. The complete suite passed **63 tests** with real PostgreSQL/pgvector and real local models enabled:

```sh
uv run --extra backend ruff format --check .
uv run --extra backend ruff check .
uv run --extra backend ty check
CONVO_TEST_POSTGRES=1 CONVO_TEST_MODELS=1 uv run --extra backend pytest -q
```

Coverage includes schema migration/backfill, hybrid branch fusion, document isolation, overview coverage, reranker rejection, exact quotation checks, citation-ID normalization, corrective retry, actual SDK wire-format serialization, session persistence across store/backend/UI restarts, failed-turn atomicity, stale append protection, old-file removal, worker process output/cancellation, and small-terminal session-picker interaction.

A live request through the existing ChatGPT account also succeeded: the model returned strict structured output, Python validated its quote, and the rendered result was `The launch code is orchid. [1]` with one cited source. This was a synthetic verification document, not a private user file.

The installed editable CLI was exercised in a real PTY: first draw took 1.08s, 0.64s and 0.66s during concurrent local checks; `/` showed commands and `/quit` exited cleanly. Session-picker and resumed-grounded-answer screenshots were rendered and visually inspected.

The normal Podman VM currently fails to start with `krunkit exited unexpectedly with exit code 2`. Therefore this session could not migrate the existing Podman database. Database/model verification used the already-installed PostgreSQL 14 + pgvector in disposable local clusters, with Alembic creating the same schema. Those clusters were stopped and removed afterward. The application's database configuration remains Podman; run the migration above when that VM/container is available.
