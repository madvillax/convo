# Changelog

## 0.1.1 — 2026-10-16

- Fix Fedora/Podman startup by using the fully qualified `docker.io/pgvector/pgvector:pg16` image. This also supports systems where `docker` is a Podman compatibility wrapper.
- Cover both Docker and Podman image creation in bootstrap regression tests.
- Add the Convo logo and an illustrated guide to opening a project folder, signing in, selecting a file, asking questions, and resuming saved sessions.
- Keep README images accessible when displayed on PyPI.
- Update the standalone landing page to Next.js, React, TypeScript, Tailwind CSS, and npm, with Geist fonts, a pure black background, and the `#FFAD00` accent.

### Install or update

```sh
uv tool install --python 3.12 convo-cli
# Existing installation:
uv tool upgrade --refresh convo-cli
```

Docker Desktop or Podman is required for Convo's managed local database. Existing conversations and local database data are preserved.
