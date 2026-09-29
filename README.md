# CONVO 

A terminal knowledge assistant that will answer questions about selected local files with path and line citations. This repository currently contains the Bun CLI scaffold and the directories for the backend you will build.

## Run the scaffold

```bash
bun install
bun run start
```

`bun run dev` watches the CLI while you work. `bun run typecheck` checks TypeScript without running tests.

## Folder map

| Path | Responsibility |
| --- | --- |
| `src/cli.ts` | Parse terminal commands, call an application use case, and print its result. |
| `src/app/` | User actions: list files, ask selected files, index, search, and ask a project. |
| `src/domain/` | Document, chunk, citation, and error types and rules, independent of tools. |
| `src/ports/` | Interfaces for files, generation, embeddings, and the index repository. |
| `src/infrastructure/files/` | Bun file access, discovery, ignore rules, and document reading. |
| `src/infrastructure/ai/` | AI SDK generation and embeddings, and a later Codex adapter. |
| `src/infrastructure/auth/` | Shared login state and credential storage, added later. |
| `src/infrastructure/database/` | PostgreSQL client, schema, and repository implementation, added later. |
| `src/rag/` | Chunking, context selection, citation checks, and ranking. |
| `src/rag/ranking/` | Vector search, keyword search, and result fusion. |
| `src/tui/` | OpenTUI screens and components, added after CLI commands work. |
| `drizzle/` | Database migrations, added when indexing is implemented. |

## Build order

1. Implement `know files` in `src/app/list-files.ts` and `src/infrastructure/files/discover-files.ts`. Apply `.knowignore`, skip secrets and dependencies, and reject paths outside the current project.
2. Add line-aware document reading and chunking. Preserve each chunk's source path and line range.
3. Implement `know ask --file ...` with context selection, generation, and citation ID validation.
4. Add PostgreSQL schema and migrations, then changed-file indexing and embeddings.
5. Add project search, project answers, login methods, and finally OpenTUI.

The architecture files are already created with responsibility comments. Implement each file when you reach its build step.
