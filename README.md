# Convo

Convo is an open-source, local-first terminal app for chatting with a selected file. Qwen3 embeddings and PostgreSQL full-text search retrieve passages together; a local cross-encoder reranks them; your connected ChatGPT account returns a structured answer with supporting quotations.

It is released under the [MIT License](LICENSE). Contributions are welcome—see [CONTRIBUTING.md](CONTRIBUTING.md).

## Install and start

The supported release install uses [uv](https://docs.astral.sh/uv/):

```sh
uv tool install "convo-rag[backend]"
convo --setup
convo
```

`convo --setup` creates a private settings file at `~/.config/convo/.env`, pulls `pgvector/pgvector:pg16`, starts a loopback-only `convo-postgres` container, and runs migrations. It generates a random database password; it does not replace or reset any existing data.

The setup command needs Docker Desktop or Podman. On macOS, it starts or initializes a Podman machine when Podman is installed. If you already use PostgreSQL, set `DATABASE_URL` to a `postgresql+psycopg://...` URL before setup; Convo will migrate that database and will not create a local container.

For a one-command install on macOS/Linux, inspect and then run the repository installer:

```sh
curl -LsSf https://raw.githubusercontent.com/madvillax/convo/main/scripts/install.sh | sh
```

It installs uv if needed, installs `convo-rag[backend]`, adds uv's tool directory to your shell path, and runs `convo --setup`. Open a new terminal if `convo` is not immediately found.

To use an unreleased checkout while developing:

```sh
uv sync --python 3.12 --extra backend
uv run --extra backend convo --setup
uv run --extra backend convo
```

`--directory ~/Documents` changes the file browser root. Environment variables always override the user settings file; `.env.example` is only for checkout-based development.

Optional model download/warmup outside the TUI:

```sh
uv run --extra backend convo --download-model
```

This prepares both Qwen3 and `cross-encoder/ms-marco-MiniLM-L6-v2`. Models otherwise load/download on demand in an isolated process. File preparation shows stages and elapsed time; Esc cancels it. Download/native logs stay in `~/.cache/convo/rag-worker.log` (respecting `XDG_CACHE_HOME`). Startup restores account preferences locally without connecting to storage, loading models, or fetching the account catalog.

For a UI preview without services or backend dependencies:

```sh
uv run convo --shell
```

## Use

Type `/` for command suggestions. Filter by typing, use ↑/↓ to move, Tab to complete, Enter to run, and Esc to dismiss.

| Command/key | Action |
| --- | --- |
| `/login` | Connect your ChatGPT account through browser sign-in |
| `/models` | Search and select an account model |
| `/models <id>` | Select a model directly |
| Ctrl+T or Shift+Tab | Cycle auto and the model's supported thinking levels |
| F2 or `/thinking` | Choose a thinking level directly |
| `/thinking high`, `/thinking auto` | Set a supported level or restore the model default |
| `/file`, Ctrl+O | Select and index a file; create a saved conversation |
| `/sessions` | Search saved conversations by title, filename, or ID and resume one |
| `/sessions <uuid>` | Resume a conversation directly |
| `/new` | Create a new saved conversation, keeping the selected file |
| `/clear` | Same behavior as `/new`; previous conversations remain saved |
| `/reset` | Create a new saved conversation without a selected file |
| Esc during file preparation | Stop preparation and restore the input |
| `/help` | Show commands and keys |
| `/quit`, `/exit`, Ctrl+C | Exit |
| PageUp / PageDown | Scroll the transcript while keeping the input focused |

Questions appear in shaded blocks with a gold left edge. Answers use spaced Markdown with highlighted code, and source quotations appear in a separate subdued block. The composer groups your input with the gold model name and thinking level underneath. The ASCII title collapses once chatting starts and in smaller terminals, leaving more room to read. Long replies open at the question and the beginning of the answer; use PageUp/PageDown or the mouse wheel to keep reading.

Change the cycling shortcut with `convo --thinking-key ctrl+g` or set `CONVO_THINKING_KEY=ctrl+g` in `.env` (export it for `--shell`). The command-line flag takes precedence. Shift+Tab and F2 remain available. Choose a Ctrl/Alt letter or F3–F24; essential keys are reserved. `/help` shows the configured shortcut. Only thinking levels supported by the selected account model can be saved.

Sessions, completed message pairs, displayed source quotes, and structured answers persist in PostgreSQL. Use `/sessions` after restarting. Resuming uses the saved indexed snapshot, so the original file can have moved or disappeared. Use `/file` again to index changed content. A failed request never saves a partial turn. Account tokens remain in the OS keyring; model/thinking preferences remain in the local account profile.

Greetings such as `hello` and acknowledgements such as `thank you` receive a short local reply without retrieval or model calls. Mixed greetings and file questions still use retrieval. Specific questions use hybrid search, reciprocal rank fusion, cross-encoder reranking, and weak-match filtering. Broad file overviews sample sections across the snapshot and rerank their order without applying a QA relevance cutoff.

ChatGPT returns JSON sections containing text and citation objects. Python validates the schema, requires citations on answered sections, checks source IDs and exact supporting quotes, then renders readable Markdown with numbered citations. Only cited quotes appear under sources. An empty evidence set returns an insufficient-evidence response without an LLM call. These checks verify structure and quotations; they do not prove every generated claim is entailed by its quote.

Supported files: `.txt`, `.md`, `.pdf`, `.docx`, `.csv`, `.json`, `.py`, `.rst`, `.log`. Limits: 10 MB input, 500,000 extracted characters, and 2,000 chunks. LlamaIndex is used only for readers and chunking. The TUI supports terminals down to 50 columns × 18 rows.

## Architecture

```text
convo/
├── core/       settings, shared values and UI/backend contracts
├── ui/         Textual app, commands, file/model/session pickers
├── llm/        ChatGPT connection, credentials, catalog and Responses transport
├── pipeline/   chat flow, routing, ingestion, embeddings, reranking and worker
├── prompts/    answer instructions, context builder and structured schema
└── db/         SQLAlchemy models, connections, document/search/session queries
```

[ARCHITECTURE.md](ARCHITECTURE.md) explains the files, schema, data flow, tuning, and verification. [changes.md](changes.md) records implementation approaches and validation.

## Checks

```sh
uv run --extra backend ruff format --check .
uv run --extra backend ruff check .
uv run --extra backend ty check
uv run --extra backend pytest -q
```

PostgreSQL integration checks use a disposable database, enabled explicitly with `CONVO_TEST_DATABASE_URL`. `CONVO_TEST_MODELS=1` also exercises real Qwen/reranking models. See [ARCHITECTURE.md](ARCHITECTURE.md) for these opt-in checks and their prerequisites.

## Releasing to PyPI

Maintainers should test a release on TestPyPI first, then create a GitHub release. The included `Publish to PyPI` workflow uses PyPI Trusted Publishing, so it does not require a long-lived token in the repository. Configure the repository and `.github/workflows/publish.yml` as a Trusted Publisher in PyPI before publishing.

```sh
uv build --no-sources
uv publish --token "$PYPI_TOKEN" # one-time/manual alternative
```
