# Convo website

The Convo landing page, kept alongside the Python CLI in this monorepo. Two main sections: installation/hero and a usage guide. Native HTML, TypeScript, and CSS with Vercel's self-hosted Geist Sans and Geist Mono fonts from Fontsource; Vite+ handles development and production builds.

From the repository root:

```sh
bun install
bun run dev       # http://127.0.0.1:3000
bun run check     # format, lint, type checks
bun run build     # apps/web/dist
bun run preview   # preview the production build
```

The Python package remains at `convo/`, with its existing `pyproject.toml` and `uv.lock`. Run it independently with `uv run convo`. No database or ChatGPT connection is needed to run the website.

Deploy `apps/web/dist` to any static host after building. This site uses real CLI commands from `convo/__main__.py` and `convo/ui/commands.py`; keep its guide in sync when those change. The terminal image is a repository screenshot, copied into tracked public assets so a fresh checkout can build independently.
