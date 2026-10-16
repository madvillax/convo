# Convo website

The Convo landing page is an independent Next.js App Router app using React, TypeScript, and Tailwind CSS v4. The hero and usage guide use Vercel's Geist Sans and Geist Mono through the official `geist` package and `next/font`.

Run from `apps/web` (use `cd apps/web` first when starting at the repository root):

```sh
npm install
npm run dev       # http://127.0.0.1:3000
npm run check     # ESLint and TypeScript checks
npm run build     # Next.js production build in .next
npm run start     # serve the production build on port 3000
npm run preview   # alias for the production server
```

This folder has its own `package.json`, `package-lock.json`, and `node_modules`. Use Node.js and npm to install and run it. The Python CLI in `convo/` uses the repository's `pyproject.toml` and `uv.lock`. Run it from the repository root with `uv run convo`. No database or ChatGPT connection is needed to run the website.

`src/app/page.tsx` composes the page as a Server Component. Small Client Components in `src/components` handle installation tabs, command categories, and clipboard feedback. Layout and responsive styling use Tailwind utilities; `globals.css` defines the theme and shared browser defaults. `postcss.config.mjs` runs the Tailwind PostCSS plugin.

For Vercel, choose `apps/web` as the project root and the Next.js framework preset. The production build also runs on any host that supports `next start`.

This site uses real CLI commands from `convo/__main__.py` and `convo/ui/commands.py`; keep its guide in sync when those change. The terminal image is a repository screenshot in tracked public assets. Fonts are bundled from the installed `geist` package, so builds do not fetch Google Fonts.
