# Elenchus Studio — Frontend

Phase 6. React + TypeScript + Vite. Local-only, single-user, no auth.

## Install

```bash
cd studio/frontend
npm install
npx playwright install chromium
```

## Develop (hot reload)

In one terminal:

```bash
python -m studio.api.server --db /tmp/studio.sqlite --port 8765
```

In another:

```bash
cd studio/frontend
npm run dev
```

Open http://localhost:5173/.

The Vite dev server proxies `/api/*` to `http://localhost:8765`. The
React app calls only `/api/*` paths — it never imports the `elenchus/`
library directly (Rule 6).

## Build for production

```bash
cd studio/frontend
npm run build
```

Outputs `studio/frontend/dist/`. When the FastAPI server (`studio/api/app.py`)
is started with that `dist/` present, it mounts the static files at `/`
and the API at `/api/*`. Both are served from the same origin.

```bash
python -m studio.api.server --db /tmp/studio.sqlite --port 8765
# Open http://localhost:8765/
```

## Tests

```bash
npm test          # vitest run (jsdom)
npm run test:watch
npm run e2e       # playwright (requires server on :8765)
```

## File layout

See `src/` for components, `src/pages/` for views, `src/hooks/` for
TanStack Query hooks, `src/api.ts` for the typed fetch wrappers, and
`src/types.ts` for the TS interfaces mirroring the Pydantic models.
