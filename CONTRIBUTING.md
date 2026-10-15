# Contributing to Convo

Contributions from students, researchers, and terminal-tool enthusiasts are welcome.

## Before opening a pull request

1. Fork the repository and create a focused branch.
2. Install the project with `uv sync --python 3.12`.
3. Keep changes focused: do not mix formatting, dependency upgrades, and unrelated features.
4. Add or update tests for changed behaviour.
5. Run the checks below from the repository root.

```sh
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -q
```

PostgreSQL and model checks are intentionally opt-in; see `ARCHITECTURE.md` for the required environment variables. Never commit `.env`, tokens, personal documents, model caches, or database dumps.

## Pull requests

Explain the user-visible change, the design trade-off, and verification performed. Keep UI code independent of database and model implementation details. If you change the data model, include a reviewed Alembic migration and explain how existing local data is preserved.

By contributing, you agree that your contribution is licensed under the repository's MIT License.
