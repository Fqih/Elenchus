# Elenchus Studio Frontend (Phase 6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal React + TypeScript + Vite frontend for Elenchus Studio so that a person with no prior context can upload a source document, paste an answer with one deliberately false claim, and correctly identify which claim was flagged and why — using only the UI.

**Architecture:** Vite dev server with `/api` proxy → FastAPI on `:8765`. Production: Vite builds to `studio/frontend/dist/`, FastAPI mounts it as StaticFiles. Frontend calls the public API via typed wrappers — never imports `elenchus/` directly (Rule 6). Server state via TanStack Query; plain CSS with CSS variables for styling.

**Tech Stack:** Vite 5+, React 18, TypeScript 5, React Router 6, TanStack Query 5, Vitest, React Testing Library, Playwright (Chromium).

**Spec:** `docs/superpowers/specs/2026-07-26-studio-frontend-design.md`

## Global Constraints

These hold for every task. (Copied verbatim from the spec.)

- **Scope (v1)**: project list + create, project detail (source docs, check, history), color-coded claims with evidence on click, run history. Side-by-side comparison deferred to v1.5.
- **Out of scope**: candidate generation, auth, multi-tenancy, hosting.
- **Rule 6**: Studio frontend never imports `elenchus/`. It only talks to the FastAPI backend over HTTP.
- **Rule 7**: Frontend is a consumer of the library, not a special case. It calls the public API exactly like any external client.
- **Rule 9**: Each phase ends with verified evidence (passing tests, E2E walk).
- **Git identity**: every commit authored by `fqih <fqihhakim@student.gunadarma.ac.id>`. No Claude co-author.
- **API base path**: all 12 endpoints are mounted under `/api/*` (not `/projects` directly). This is required so that the FastAPI static-files mount at `/` doesn't shadow the API.
- **API token**: React code calls `/api/projects` etc. In dev, Vite proxies `/api` → `http://localhost:8765`. In prod, FastAPI serves both the static `dist/` and the `/api/*` routes.
- **No codegen**: TS types are hand-typed from the Pydantic models in `studio/api/app.py:43-103`. If a Pydantic field changes, the TS interface must be updated by hand.
- **Real NLI**: the Phase 5 smoke test uses the real cross-encoder NLI model. The Phase 6 E2E test follows the same convention.

---

## File Structure

```
studio/
├── frontend/                                   ← NEW (Node.js, package.json)
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── vitest.config.ts
│   ├── playwright.config.ts
│   ├── index.html
│   ├── README.md
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api.ts
│   │   ├── types.ts
│   │   ├── theme.css
│   │   ├── index.css
│   │   ├── pages/
│   │   │   ├── ProjectList.tsx
│   │   │   └── ProjectDetail.tsx
│   │   ├── components/
│   │   │   ├── ProjectForm.tsx
│   │   │   ├── SourceDocForm.tsx
│   │   │   ├── SourceDocList.tsx
│   │   │   ├── CheckForm.tsx
│   │   │   ├── RunResult.tsx
│   │   │   ├── ClaimSpan.tsx
│   │   │   ├── EvidencePanel.tsx
│   │   │   ├── RunHistory.tsx
│   │   │   └── GateBadge.tsx
│   │   └── hooks/
│   │       └── useStudioApi.ts
│   ├── tests/
│   │   ├── api.test.ts
│   │   ├── useStudioApi.test.tsx
│   │   ├── ClaimSpan.test.tsx
│   │   ├── GateBadge.test.tsx
│   │   ├── EvidencePanel.test.tsx
│   │   └── RunResult.test.tsx
│   └── e2e/
│       └── studio_frontend_smoke.spec.ts
└── examples/
    └── studio_frontend_smoke_test.ts           ← NEW (Playwright runner)

studio/api/
├── app.py                                      ← MODIFIED (APIRouter prefix, CORS, static mount)
└── server.py                                   ← UNCHANGED

studio/tests/
└── test_api.py                                 ← MODIFIED (paths to /api/*)

studio/examples/
└── studio_smoke_test.py                        ← MODIFIED (paths to /api/*)

studio/README.md                                ← MODIFIED (updated endpoint table)
```

---

## Task 1: Refactor Studio API to `/api/*` prefix + add CORS + static mount

**Files:**
- Modify: `studio/api/app.py:1-378`
- Modify: `studio/tests/test_api.py:1-200`
- Modify: `studio/examples/studio_smoke_test.py:95-240`
- Modify: `studio/README.md:26-95`

**Why first**: the frontend needs the API at `/api/*`. FastAPI mounts static files at `/`, so the API and static files must live at different paths to avoid the static mount shadowing the API routes.

**Interfaces:** no new interfaces; this task changes the URL surface only.

### Step 1: Update the failing test

In `studio/tests/test_api.py`, change every client call to use the `/api` prefix. Examples:

```python
# OLD
r = client.post("/projects", json={"name": "kb"})
# NEW
r = client.post("/api/projects", json={"name": "kb"})
```

Apply the same change to:
- `client.get("/projects")` → `client.get("/api/projects")`
- `client.get(f"/projects/{project_id}")` → `client.get(f"/api/projects/{project_id}")`
- `client.post(f"/projects/{project_id}/source-documents", ...)` → `client.post(f"/api/projects/{project_id}/source-documents", ...)`
- `client.get(f"/projects/{project_id}/source-documents")` → `client.get(f"/api/projects/{project_id}/source-documents")`
- `client.get(f"/projects/{project_id}/source-documents/{sid}")` → `client.get(f"/api/projects/{project_id}/source-documents/{sid}")`
- `client.patch(f"/projects/{project_id}/source-documents/{sid}", ...)` → `client.patch(f"/api/projects/{project_id}/source-documents/{sid}", ...)`
- `client.post(f"/projects/{project_id}/checks", ...)` → `client.post(f"/api/projects/{project_id}/checks", ...)`
- `client.get(f"/projects/{project_id}/runs")` → `client.get(f"/api/projects/{project_id}/runs")`
- `client.get(f"/runs/{run_id}")` → `client.get(f"/api/runs/{run_id}")`
- `client.get(f"/projects/{project_id}/gate-policy")` → `client.get(f"/api/projects/{project_id}/gate-policy")`
- `client.put(f"/projects/{project_id}/gate-policy", ...)` → `client.put(f"/api/projects/{project_id}/gate-policy", ...)`

### Step 2: Run tests to verify they fail

```bash
LD_LIBRARY_PATH=$HOME/.local/lib python -m pytest studio/tests/test_api.py -v
```

Expected: all tests FAIL with 404 (routes not found at `/projects`).

### Step 3: Refactor `studio/api/app.py` to use APIRouter

Add these imports at the top:

```python
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
```

Inside `create_app`, before defining any routes, create an APIRouter:

```python
    api = APIRouter(prefix="/api")
```

Add CORS middleware after `app = FastAPI(...)`:

```python
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

Replace every `@app.<method>(...)` with `@api.<method>(...)`. For example:

```python
# OLD
@app.post("/projects", response_model=ProjectResponse)
def create_project(req: CreateProjectRequest) -> dict:
    ...

# NEW
@api.post("/projects", response_model=ProjectResponse)
def create_project(req: CreateProjectRequest) -> dict:
    ...
```

Apply the same change to all 12 endpoints.

After the APIRouter is fully defined (still inside `create_app`), add the static-files mount (only if the dist directory exists, so tests don't need a build):

```python
    app.include_router(api)

    dist_dir = Path(__file__).parent.parent / "frontend" / "dist"
    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="frontend")

    return app
```

Update the module docstring at the top of `app.py` to reflect the new paths:

```python
"""Studio FastAPI app.

Endpoints (all under /api):

- POST /api/projects                                       — create project
- GET  /api/projects                                       — list projects
- GET  /api/projects/{project_id}                          — get project
- POST /api/projects/{project_id}/source-documents         — add source doc
- GET  /api/projects/{project_id}/source-documents         — list source docs
- GET  /api/projects/{project_id}/source-documents/{sid}   — get source doc (latest by default)
- PATCH /api/projects/{project_id}/source-documents/{sid}  — edit source doc (bumps version)
- POST /api/projects/{project_id}/checks                   — submit a check
- GET  /api/projects/{project_id}/runs                     — list run history
- GET  /api/runs/{run_id}                                  — get a single run
- GET  /api/projects/{project_id}/gate-policy              — get gate policy
- PUT  /api/projects/{project_id}/gate-policy              — set gate policy

Per Rule 7, the handler that submits a check uses only the public
`elenchus.verifier.Verifier` API (verify + verify_claim). Internal
modules are not touched.
"""
```

### Step 4: Run tests to verify they pass

```bash
LD_LIBRARY_PATH=$HOME/.local/lib python -m pytest studio/tests -v
```

Expected: 50 passed (the same 50 tests as before, now against `/api/*`).

### Step 5: Update the E2E smoke test

In `studio/examples/studio_smoke_test.py`, replace every URL string with its `/api` equivalent. Examples:

```python
# OLD
client.post("/projects", json={"name": "kb-smoke"})
# NEW
client.post("/api/projects", json={"name": "kb-smoke"})
```

Apply the same change to all 12 endpoint paths in the file. The starting print banner can stay as `Phase 5` — Phase 6 will add a new smoke test for the UI.

### Step 6: Run the smoke test to verify it still passes

```bash
LD_LIBRARY_PATH=$HOME/.local/lib python -m studio.examples.studio_smoke_test
```

Expected: prints `all acceptance checks passed`, exits 0.

### Step 7: Update `studio/README.md`

Replace the endpoint table at `studio/README.md:26-39` so every path is prefixed with `/api`:

```markdown
| Method | Path                                                       | Purpose |
|-------:|------------------------------------------------------------|---------|
| POST   | `/api/projects`                                            | Create a project |
| GET    | `/api/projects`                                            | List projects |
| GET    | `/api/projects/{project_id}`                               | Get a project |
| POST   | `/api/projects/{project_id}/source-documents`              | Add a source document (gets v1) |
| GET    | `/api/projects/{project_id}/source-documents`              | List current source documents |
| GET    | `/api/projects/{project_id}/source-documents/{sid}`        | Get a source document (latest by default, `?version=N` for older) |
| PATCH  | `/api/projects/{project_id}/source-documents/{sid}`        | Edit a source document (bumps version) |
| POST   | `/api/projects/{project_id}/checks`                        | Submit a check (runs the library + output gate) |
| GET    | `/api/projects/{project_id}/runs`                          | List run history (chronological order) |
| GET    | `/api/runs/{run_id}`                                       | Get a single run including its verdicts |
| GET    | `/api/projects/{project_id}/gate-policy`                   | Get the project's output-gate policy |
| PUT    | `/api/projects/{project_id}/gate-policy`                   | Set the project's output-gate policy |
```

Add a sentence at the end of the "Run the server" section explaining the SPA:

```markdown
If `studio/frontend/dist/` exists (run `npm run build` in `studio/frontend/`),
the FastAPI process also serves the React frontend at `/`. CORS is enabled
for the Vite dev server (`http://localhost:5173`). The 12 API endpoints live
under `/api/*`.
```

### Step 8: Commit

```bash
git add studio/api/app.py studio/tests/test_api.py studio/examples/studio_smoke_test.py studio/README.md
git commit -m "studio: prefix API routes with /api, add CORS and static mount

The API routes move from /projects/* to /api/projects/* so that FastAPI
can mount the Phase 6 React build at / without the static handler
shadowing the API.

Also adds:
  - CORS middleware for the Vite dev server (localhost:5173)
  - Optional StaticFiles mount at / when studio/frontend/dist exists
  - Updated test paths and Phase 5 smoke test URLs
  - Updated README endpoint table

All 50 Phase 5 tests still pass; the Python smoke test still prints
'all acceptance checks passed'."
```

---

## Task 2: Vite scaffold + dependencies + dev/prod config

**Files:**
- Create: `studio/frontend/package.json` (from `npm create vite`)
- Create: `studio/frontend/tsconfig.json`
- Create: `studio/frontend/vite.config.ts`
- Create: `studio/frontend/vitest.config.ts`
- Create: `studio/frontend/index.html`
- Create: `studio/frontend/src/main.tsx` (placeholder)
- Create: `studio/frontend/src/App.tsx` (placeholder)
- Create: `studio/frontend/src/index.css` (reset)

**Why second**: scaffold the project before any code is written. Once the dev server is up, every subsequent task can be visually verified.

**Interfaces:** none yet — placeholder content.

### Step 1: Run Vite scaffold non-interactively

```bash
cd /home/faqihhakim/Project/Elenchus
npm create vite@latest studio/frontend -- --template react-ts
```

Expected: creates `studio/frontend/` with `package.json`, `tsconfig.json`, `vite.config.ts`, `index.html`, `src/`, `public/`.

### Step 2: Install runtime dependencies

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm install react-router-dom@^6 @tanstack/react-query@^5
```

Expected: `package.json` now lists `react-router-dom` and `@tanstack/react-query` under `dependencies`.

### Step 3: Install dev dependencies

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm install -D vitest@^1 @testing-library/react@^14 @testing-library/jest-dom@^6 @testing-library/user-event@^14 jsdom@^24 @playwright/test@^1
```

Expected: `package.json` now lists those under `devDependencies`.

### Step 4: Update `package.json` scripts

Edit `studio/frontend/package.json` so the `scripts` block reads:

```json
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "e2e": "playwright test",
    "typecheck": "tsc -b --noEmit"
  },
```

### Step 5: Configure Vite with the API proxy

Replace `studio/frontend/vite.config.ts` with:

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8765",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
```

### Step 6: Configure Vitest

Create `studio/frontend/vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
```

Create `studio/frontend/tests/setup.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
```

### Step 7: Configure TypeScript

Replace `studio/frontend/tsconfig.json` with the Vite default plus these tweaks:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "tests"],
  "exclude": ["e2e", "dist"]
}
```

### Step 8: Replace the placeholder `src/main.tsx`

Replace `studio/frontend/src/main.tsx` with:

```typescript
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

Replace `studio/frontend/src/App.tsx` with:

```typescript
export default function App() {
  return <div className="app">Elenchus Studio frontend scaffolded.</div>;
}
```

Replace `studio/frontend/src/index.css` with:

```css
*, *::before, *::after { box-sizing: border-box; }
html, body, #root { margin: 0; padding: 0; height: 100%; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
```

### Step 9: Verify the dev server compiles

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm run build
```

Expected: `dist/` directory is created with `index.html` and a `assets/` folder. `npm run typecheck` exits 0.

### Step 10: Add `.gitignore` updates

Read the existing `studio/frontend/.gitignore` (created by Vite scaffold). It already excludes `node_modules`, `dist`, etc. Confirm by running:

```bash
cat /home/faqihhakim/Project/Elenchus/studio/frontend/.gitignore
```

Expected to see: `node_modules`, `dist`, `dist-ssr`, `*.local`. Add these lines if missing:

```
test-results/
playwright-report/
playwright/.cache/
```

### Step 11: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/package.json studio/frontend/package-lock.json studio/frontend/tsconfig.json studio/frontend/vite.config.ts studio/frontend/vitest.config.ts studio/frontend/index.html studio/frontend/src/main.tsx studio/frontend/src/App.tsx studio/frontend/src/index.css studio/frontend/tests/setup.ts studio/frontend/.gitignore
git commit -m "studio frontend: scaffold vite + react + ts + vitest + playwright

Vite 5 + React 18 + TypeScript 5 chosen per design spec.

  - npm run dev: Vite dev server on :5173 with /api proxy to :8765
  - npm run build: tsc -b && vite build → studio/frontend/dist/
  - npm test: vitest run (jsdom + @testing-library/jest-dom)
  - npm run e2e: playwright test (Chromium, configured in Task 12)

Placeholder App.tsx renders 'Elenchus Studio frontend scaffolded.' so
that 'npm run build' produces a valid dist/. Real UI comes in subsequent
tasks."
```

---

## Task 3: TypeScript types + theme

**Files:**
- Create: `studio/frontend/src/types.ts`
- Create: `studio/frontend/src/theme.css`
- Modify: `studio/frontend/src/index.css` (import theme)

**Why third**: types and theme are foundational. Every component references them.

**Interfaces:** exports the 5 TS interfaces copied from the spec.

### Step 1: Write `src/types.ts`

Create `studio/frontend/src/types.ts`:

```typescript
export type VerdictLabel = "entailed" | "contradicted" | "unverifiable";
export type GateResult = "allowed" | "flagged" | "blocked";
export type Tier = "nli" | "judge";

export interface Claim {
  id: string;
  text: string;
  span: [number, number];
}

export interface Evidence {
  source_id: string;
  text: string;
  span: [number, number];
}

export interface Verdict {
  claim: Claim;
  label: VerdictLabel;
  confidence: number;
  tier: Tier;
  evidence: Evidence | null;
  checked_at: string;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
}

export interface SourceDocument {
  id: string;
  project_id: string;
  name: string;
  content: string;
  content_sha256: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Run {
  id: string;
  project_id: string;
  question: string | null;
  model_or_prompt_label: string;
  candidate_answer: string;
  source_document_versions: Record<string, number>;
  verdicts: Verdict[];
  gate_result: GateResult;
  latency_ms: number;
  created_at: string;
}

export interface GatePolicy {
  block_on_any_contradiction: boolean;
  flag_if_unverifiable_count_exceeds: number;
}
```

### Step 2: Write `src/theme.css`

Create `studio/frontend/src/theme.css`:

```css
:root {
  --color-bg: #ffffff;
  --color-fg: #1a1a1a;
  --color-muted: #6b7280;
  --color-border: #e5e7eb;
  --color-accent: #2563eb;
  --color-accent-fg: #ffffff;

  --color-allowed-bg: #dcfce7;
  --color-allowed-fg: #14532d;
  --color-allowed-border: #bbf7d0;

  --color-flagged-bg: #fef3c7;
  --color-flagged-fg: #78350f;
  --color-flagged-border: #fde68a;

  --color-blocked-bg: #fee2e2;
  --color-blocked-fg: #7f1d1d;
  --color-blocked-border: #fecaca;

  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;

  --radius: 6px;
  --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
}
```

### Step 3: Update `src/index.css` to import theme

Replace `studio/frontend/src/index.css` with:

```css
@import "./theme.css";

*, *::before, *::after { box-sizing: border-box; }
html, body, #root { margin: 0; padding: 0; height: 100%; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--color-bg);
  color: var(--color-fg);
}
```

### Step 4: Verify the build

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm run build
```

Expected: succeeds, `dist/index.html` is generated.

### Step 5: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/src/types.ts studio/frontend/src/theme.css studio/frontend/src/index.css
git commit -m "studio frontend: types + theme

types.ts mirrors the Pydantic models in studio/api/app.py:43-103.
Hand-typed, no codegen — 12 endpoints is cheap to maintain.

theme.css exposes color tokens for the verdict classes:
  --color-allowed-bg/-fg/-border
  --color-flagged-bg/-fg/-border
  --color-blocked-bg/-fg/-border
Plus spacing, radius, and font-mono tokens."
```

---

## Task 4: API client (`src/api.ts`) + tests

**Files:**
- Create: `studio/frontend/src/api.ts`
- Create: `studio/frontend/tests/api.test.ts`

**Why fourth**: every other component depends on the typed fetch wrappers. Test the wrappers first.

**Interfaces:** 12 exported functions, all returning Promises. Each takes a typed request body where applicable, returns the matching interface from `types.ts`. The internal `apiCall<T>(path, init)` throws `ApiError` on non-2xx.

### Step 1: Write the failing test

Create `studio/frontend/tests/api.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  createProject,
  listProjects,
  getProject,
  addSourceDocument,
  listSourceDocuments,
  getSourceDocument,
  updateSourceDocument,
  submitCheck,
  getRun,
  listRuns,
  getGatePolicy,
  setGatePolicy,
} from "../src/api";

const originalFetch = global.fetch;

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    ),
  ) as unknown as typeof fetch;
});

afterEach(() => {
  global.fetch = originalFetch;
});

describe("apiCall", () => {
  it("createProject POSTs to /api/projects with the name", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "p1", name: "kb", created_at: "t" }), {
        status: 200,
      }),
    );
    const p = await createProject({ name: "kb" });
    expect(p.id).toBe("p1");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
        body: JSON.stringify({ name: "kb" }),
      }),
    );
  });

  it("listProjects GETs /api/projects", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify([]), { status: 200 }),
    );
    await listProjects();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("throws ApiError with parsed detail on 4xx", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "project not found" }), {
        status: 404,
      }),
    );
    await expect(getProject("missing")).rejects.toThrow("project not found");
  });

  it("addSourceDocument POSTs to /api/projects/:id/source-documents", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "d1",
          project_id: "p1",
          name: "kb",
          content: "x",
          content_sha256: "abc",
          version: 1,
          created_at: "t",
          updated_at: "t",
        }),
        { status: 200 },
      ),
    );
    await addSourceDocument("p1", { name: "kb", content: "x" });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/source-documents",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("updateSourceDocument PATCHes with the new content", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "d1", version: 2 }), { status: 200 }),
    );
    await updateSourceDocument("p1", "d1", { content: "new" });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/source-documents/d1",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ content: "new" }) }),
    );
  });

  it("getSourceDocument includes ?version=N when supplied", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "d1", version: 1 }), { status: 200 }),
    );
    await getSourceDocument("p1", "d1", 1);
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/source-documents/d1?version=1",
      expect.any(Object),
    );
  });

  it("submitCheck POSTs to /api/projects/:id/checks", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "r1",
          project_id: "p1",
          question: "q",
          model_or_prompt_label: "gpt",
          candidate_answer: "a",
          source_document_versions: {},
          verdicts: [],
          gate_result: "allowed",
          latency_ms: 10,
          created_at: "t",
        }),
        { status: 200 },
      ),
    );
    await submitCheck("p1", {
      question: "q",
      model_or_prompt_label: "gpt",
      candidate_answer: "a",
    });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/checks",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("getRun GETs /api/runs/:id", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "r1" }), { status: 200 }),
    );
    await getRun("r1");
    expect(global.fetch).toHaveBeenCalledWith("/api/runs/r1", expect.any(Object));
  });

  it("listRuns GETs /api/projects/:id/runs", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(JSON.stringify([]), { status: 200 }),
    );
    await listRuns("p1");
    expect(global.fetch).toHaveBeenCalledWith("/api/projects/p1/runs", expect.any(Object));
  });

  it("getGatePolicy GETs /api/projects/:id/gate-policy", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          block_on_any_contradiction: true,
          flag_if_unverifiable_count_exceeds: 1,
        }),
        { status: 200 },
      ),
    );
    await getGatePolicy("p1");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/gate-policy",
      expect.any(Object),
    );
  });

  it("setGatePolicy PUTs to /api/projects/:id/gate-policy", async () => {
    (global.fetch as any).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          block_on_any_contradiction: false,
          flag_if_unverifiable_count_exceeds: 0,
        }),
        { status: 200 },
      ),
    );
    await setGatePolicy("p1", {
      block_on_any_contradiction: false,
      flag_if_unverifiable_count_exceeds: 0,
    });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/projects/p1/gate-policy",
      expect.objectContaining({ method: "PUT" }),
    );
  });
});
```

### Step 2: Run tests to verify they fail

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm test
```

Expected: tests fail with "Cannot find module '../src/api'".

### Step 3: Write `src/api.ts`

Create `studio/frontend/src/api.ts`:

```typescript
import type {
  Project,
  SourceDocument,
  Run,
  GatePolicy,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiCall<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // body was not JSON
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

// ---- Projects ----------------------------------------------------------

export function createProject(req: { name: string }): Promise<Project> {
  return apiCall<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function listProjects(): Promise<Project[]> {
  return apiCall<Project[]>("/api/projects");
}

export function getProject(projectId: string): Promise<Project> {
  return apiCall<Project>(`/api/projects/${projectId}`);
}

// ---- Source documents --------------------------------------------------

export function addSourceDocument(
  projectId: string,
  req: { name: string; content: string },
): Promise<SourceDocument> {
  return apiCall<SourceDocument>(
    `/api/projects/${projectId}/source-documents`,
    { method: "POST", body: JSON.stringify(req) },
  );
}

export function listSourceDocuments(projectId: string): Promise<SourceDocument[]> {
  return apiCall<SourceDocument[]>(`/api/projects/${projectId}/source-documents`);
}

export function getSourceDocument(
  projectId: string,
  sourceId: string,
  version?: number,
): Promise<SourceDocument> {
  const query = version !== undefined ? `?version=${version}` : "";
  return apiCall<SourceDocument>(
    `/api/projects/${projectId}/source-documents/${sourceId}${query}`,
  );
}

export function updateSourceDocument(
  projectId: string,
  sourceId: string,
  req: { content: string },
): Promise<SourceDocument> {
  return apiCall<SourceDocument>(
    `/api/projects/${projectId}/source-documents/${sourceId}`,
    { method: "PATCH", body: JSON.stringify(req) },
  );
}

// ---- Checks / runs -----------------------------------------------------

export function submitCheck(
  projectId: string,
  req: {
    question?: string | null;
    model_or_prompt_label: string;
    candidate_answer: string;
  },
): Promise<Run> {
  return apiCall<Run>(`/api/projects/${projectId}/checks`, {
    method: "POST",
    body: JSON.stringify({
      question: req.question ?? null,
      model_or_prompt_label: req.model_or_prompt_label,
      candidate_answer: req.candidate_answer,
    }),
  });
}

export function getRun(runId: string): Promise<Run> {
  return apiCall<Run>(`/api/runs/${runId}`);
}

export function listRuns(projectId: string): Promise<Run[]> {
  return apiCall<Run[]>(`/api/projects/${projectId}/runs`);
}

// ---- Gate policy -------------------------------------------------------

export function getGatePolicy(projectId: string): Promise<GatePolicy> {
  return apiCall<GatePolicy>(`/api/projects/${projectId}/gate-policy`);
}

export function setGatePolicy(
  projectId: string,
  policy: GatePolicy,
): Promise<GatePolicy> {
  return apiCall<GatePolicy>(`/api/projects/${projectId}/gate-policy`, {
    method: "PUT",
    body: JSON.stringify(policy),
  });
}
```

### Step 4: Run tests to verify they pass

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm test
```

Expected: 11 tests pass.

### Step 5: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/src/api.ts studio/frontend/tests/api.test.ts
git commit -m "studio frontend: api client + tests

src/api.ts wraps fetch with an apiCall<T> helper that:
  - sets Content-Type: application/json
  - throws ApiError(status, detail) on non-2xx, parsing {detail}
  - returns parsed JSON on 2xx

12 typed wrappers, one per backend endpoint. All call /api/* paths.

11 tests cover: POST shape, GET shape, query parameters, PATCH body,
4xx error parsing, route prefix on every endpoint."
```

---

## Task 5: TanStack Query hooks (`src/hooks/useStudioApi.ts`) + tests

**Files:**
- Create: `studio/frontend/src/hooks/useStudioApi.ts`
- Create: `studio/frontend/tests/useStudioApi.test.tsx`

**Why fifth**: components consume these hooks. They isolate the server-state glue from the components.

**Interfaces:** exports `useProjects`, `useProject`, `useSourceDocuments`, `useSourceDocument`, `useRuns`, `useRun`, `useGatePolicy`, `useCreateProject`, `useAddSourceDocument`, `useUpdateSourceDocument`, `useSubmitCheck`, `useSetGatePolicy`. Each hook returns the standard TanStack Query result.

### Step 1: Write the failing test

Create `studio/frontend/tests/useStudioApi.test.tsx`:

```typescript
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useProjects, useCreateProject } from "../src/hooks/useStudioApi";

const originalFetch = global.fetch;

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  global.fetch = jest_fetch_ok({ id: "p1", name: "kb", created_at: "t" });
});

afterEach(() => {
  global.fetch = originalFetch;
});

function jest_fetch_ok(body: any) {
  return ((url: any, init: any) =>
    Promise.resolve(
      new Response(typeof body === "string" ? body : JSON.stringify(body), {
        status: 200,
      }),
    )) as unknown as typeof fetch;
}

describe("useProjects", () => {
  it("fetches /api/projects and returns the JSON", async () => {
    global.fetch = jest_fetch_ok([{ id: "p1", name: "kb", created_at: "t" }]);
    const { result } = renderHook(() => useProjects(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([{ id: "p1", name: "kb", created_at: "t" }]);
  });
});

describe("useCreateProject", () => {
  it("POSTs the name and returns the new project", async () => {
    let captured: any = null;
    global.fetch = (async (_url: any, init: any) => {
      captured = init;
      return new Response(
        JSON.stringify({ id: "p2", name: "new", created_at: "t" }),
        { status: 200 },
      );
    }) as unknown as typeof fetch;
    const { result } = renderHook(() => useCreateProject(), { wrapper: wrapper() });
    await result.current.mutateAsync({ name: "new" });
    expect(captured.method).toBe("POST");
    expect(captured.body).toBe(JSON.stringify({ name: "new" }));
  });
});
```

### Step 2: Run tests to verify they fail

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm test
```

Expected: tests fail with "Cannot find module '../src/hooks/useStudioApi'".

### Step 3: Write `src/hooks/useStudioApi.ts`

Create `studio/frontend/src/hooks/useStudioApi.ts`:

```typescript
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import * as api from "../api";
import type { Project, Run, SourceDocument, GatePolicy } from "../types";

export function useProjects(): UseQueryResult<Project[], Error> {
  return useQuery({ queryKey: ["projects"], queryFn: api.listProjects });
}

export function useProject(projectId: string): UseQueryResult<Project, Error> {
  return useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    enabled: !!projectId,
  });
}

export function useSourceDocuments(
  projectId: string,
): UseQueryResult<SourceDocument[], Error> {
  return useQuery({
    queryKey: ["source-docs", projectId],
    queryFn: () => api.listSourceDocuments(projectId),
    enabled: !!projectId,
  });
}

export function useSourceDocument(
  projectId: string,
  sourceId: string,
  version?: number,
): UseQueryResult<SourceDocument, Error> {
  return useQuery({
    queryKey: ["source-doc", projectId, sourceId, version ?? "latest"],
    queryFn: () => api.getSourceDocument(projectId, sourceId, version),
    enabled: !!projectId && !!sourceId,
  });
}

export function useRuns(projectId: string): UseQueryResult<Run[], Error> {
  return useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => api.listRuns(projectId),
    enabled: !!projectId,
  });
}

export function useRun(runId: string): UseQueryResult<Run, Error> {
  return useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId),
    enabled: !!runId,
  });
}

export function useGatePolicy(
  projectId: string,
): UseQueryResult<GatePolicy, Error> {
  return useQuery({
    queryKey: ["gate-policy", projectId],
    queryFn: () => api.getGatePolicy(projectId),
    enabled: !!projectId,
  });
}

// ---- Mutations --------------------------------------------------------

export function useCreateProject(): UseMutationResult<Project, Error, { name: string }> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createProject,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useAddSourceDocument(
  projectId: string,
): UseMutationResult<SourceDocument, Error, { name: string; content: string }> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req) => api.addSourceDocument(projectId, req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["source-docs", projectId] }),
  });
}

export function useUpdateSourceDocument(
  projectId: string,
  sourceId: string,
): UseMutationResult<SourceDocument, Error, { content: string }> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req) => api.updateSourceDocument(projectId, sourceId, req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["source-docs", projectId] }),
  });
}

export function useSubmitCheck(
  projectId: string,
): UseMutationResult<Run, Error, { question?: string | null; model_or_prompt_label: string; candidate_answer: string }> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req) => api.submitCheck(projectId, req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs", projectId] }),
  });
}

export function useSetGatePolicy(
  projectId: string,
): UseMutationResult<GatePolicy, Error, GatePolicy> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (policy) => api.setGatePolicy(projectId, policy),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["gate-policy", projectId] }),
  });
}
```

### Step 4: Run tests to verify they pass

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm test
```

Expected: 13 tests pass (11 from Task 4 + 2 from this task).

### Step 5: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/src/hooks/useStudioApi.ts studio/frontend/tests/useStudioApi.test.tsx
git commit -m "studio frontend: TanStack Query hooks + tests

useStudioApi.ts wraps the 12 api.ts functions with React Query:

  - 7 query hooks (useProjects, useProject, useSourceDocuments,
    useSourceDocument, useRuns, useRun, useGatePolicy)
  - 5 mutation hooks (useCreateProject, useAddSourceDocument,
    useUpdateSourceDocument, useSubmitCheck, useSetGatePolicy)

Mutations invalidate the relevant query keys on success so the
affected lists refresh automatically.

2 tests prove the wiring: useProjects returns the parsed JSON,
useCreateProject POSTs the body correctly."
```

---

## Task 6: Primitive components (GateBadge, ClaimSpan, EvidencePanel) + tests

**Files:**
- Create: `studio/frontend/src/components/GateBadge.tsx`
- Create: `studio/frontend/src/components/ClaimSpan.tsx`
- Create: `studio/frontend/src/components/EvidencePanel.tsx`
- Create: `studio/frontend/src/components/App.css` (component-shared layout)
- Create: `studio/frontend/tests/GateBadge.test.tsx`
- Create: `studio/frontend/tests/ClaimSpan.test.tsx`
- Create: `studio/frontend/tests/EvidencePanel.test.tsx`

**Why sixth**: the three primitives are reused across pages. Their class names are the contract every other component depends on.

**Interfaces:**

- `GateBadge({ result: GateResult })` renders `<span class="gate-badge gate-{result}">`
- `ClaimSpan({ claim: Claim, label: VerdictLabel, onClick: () => void })` renders clickable claim with `class="claim claim-{label}"`
- `EvidencePanel({ verdict: Verdict, onClose: () => void })` renders the side panel with claim text, label, confidence, evidence span, source_id link

### Step 1: Write the failing tests

Create `studio/frontend/tests/GateBadge.test.tsx`:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { GateBadge } from "../src/components/GateBadge";

describe("GateBadge", () => {
  it("applies gate-blocked class for blocked", () => {
    render(<GateBadge result="blocked" />);
    expect(screen.getByText("blocked")).toHaveClass("gate-blocked");
  });
  it("applies gate-flagged class for flagged", () => {
    render(<GateBadge result="flagged" />);
    expect(screen.getByText("flagged")).toHaveClass("gate-flagged");
  });
  it("applies gate-allowed class for allowed", () => {
    render(<GateBadge result="allowed" />);
    expect(screen.getByText("allowed")).toHaveClass("gate-allowed");
  });
});
```

Create `studio/frontend/tests/ClaimSpan.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ClaimSpan } from "../src/components/ClaimSpan";

const claim = {
  id: "c1",
  text: "Shipping takes 1 to 2 days.",
  span: [0, 30] as [number, number],
};

describe("ClaimSpan", () => {
  it("renders claim text with correct verdict class", () => {
    render(<ClaimSpan claim={claim} label="contradicted" onClick={() => {}} />);
    expect(screen.getByText("Shipping takes 1 to 2 days.")).toHaveClass("claim-contradicted");
  });
  it("invokes onClick when clicked", () => {
    const handler = vi.fn();
    render(<ClaimSpan claim={claim} label="contradicted" onClick={handler} />);
    fireEvent.click(screen.getByText("Shipping takes 1 to 2 days."));
    expect(handler).toHaveBeenCalledOnce();
  });
});
```

Create `studio/frontend/tests/EvidencePanel.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EvidencePanel } from "../src/components/EvidencePanel";

const verdict = {
  claim: { id: "c1", text: "1 to 2 days.", span: [0, 12] as [number, number] },
  label: "contradicted" as const,
  confidence: 0.95,
  tier: "nli" as const,
  evidence: {
    source_id: "d1",
    text: "3 to 5 business days.",
    span: [0, 22] as [number, number],
  },
  checked_at: "t",
};

describe("EvidencePanel", () => {
  it("renders the claim text and evidence excerpt", () => {
    render(<EvidencePanel verdict={verdict} onClose={() => {}} />);
    expect(screen.getByText("1 to 2 days.")).toBeInTheDocument();
    expect(screen.getByText("3 to 5 business days.")).toBeInTheDocument();
  });
  it("invokes onClose when close button clicked", () => {
    const handler = vi.fn();
    render(<EvidencePanel verdict={verdict} onClose={handler} />);
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(handler).toHaveBeenCalledOnce();
  });
  it("shows 'no evidence available' when evidence is null", () => {
    render(
      <EvidencePanel
        verdict={{ ...verdict, evidence: null }}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/no evidence available/i)).toBeInTheDocument();
  });
});
```

### Step 2: Run tests to verify they fail

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm test
```

Expected: 3 tests fail (GateBadge × 3, ClaimSpan × 2, EvidencePanel × 3) with "Cannot find module".

### Step 3: Write `src/components/App.css`

Create `studio/frontend/src/components/App.css`:

```css
@import "../theme.css";

/* ---- Gate badge ---- */

.gate-badge {
  display: inline-block;
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius);
  font-size: 0.875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.025em;
  border: 1px solid;
}

.gate-badge.gate-allowed {
  background: var(--color-allowed-bg);
  color: var(--color-allowed-fg);
  border-color: var(--color-allowed-border);
}

.gate-badge.gate-flagged {
  background: var(--color-flagged-bg);
  color: var(--color-flagged-fg);
  border-color: var(--color-flagged-border);
}

.gate-badge.gate-blocked {
  background: var(--color-blocked-bg);
  color: var(--color-blocked-fg);
  border-color: var(--color-blocked-border);
}

/* ---- Claim span (clickable, verdict-colored) ---- */

.claim {
  display: inline;
  padding: 0.05em 0.18em;
  margin: 0 0.05em;
  border-radius: 3px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: border-color 0.1s ease-in-out;
}

.claim:hover { border-bottom-color: currentColor; }

.claim.claim-entailed {
  background: var(--color-allowed-bg);
  color: var(--color-allowed-fg);
}

.claim.claim-contradicted {
  background: var(--color-blocked-bg);
  color: var(--color-blocked-fg);
  font-weight: 600;
}

.claim.claim-unverifiable {
  background: var(--color-flagged-bg);
  color: var(--color-flagged-fg);
}

/* ---- Evidence panel ---- */

.evidence-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 28rem;
  max-width: 90vw;
  padding: var(--space-6);
  background: var(--color-bg);
  border-left: 1px solid var(--color-border);
  box-shadow: -2px 0 16px rgba(0, 0, 0, 0.06);
  overflow-y: auto;
  z-index: 100;
}

.evidence-panel header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}

.evidence-panel button.close {
  background: none;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-1) var(--space-2);
  cursor: pointer;
}

.evidence-panel .meta {
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: var(--color-muted);
  margin-bottom: var(--space-4);
}

.evidence-panel .evidence-excerpt {
  background: #f3f4f6;
  border-left: 3px solid var(--color-accent);
  padding: var(--space-3);
  border-radius: var(--radius);
  font-family: var(--font-mono);
  font-size: 0.875rem;
  white-space: pre-wrap;
}

.evidence-panel .no-evidence {
  color: var(--color-muted);
  font-style: italic;
}
```

### Step 4: Write `src/components/GateBadge.tsx`

Create `studio/frontend/src/components/GateBadge.tsx`:

```typescript
import type { GateResult } from "../types";
import "./App.css";

export function GateBadge({ result }: { result: GateResult }) {
  return <span className={`gate-badge gate-${result}`}>{result}</span>;
}
```

### Step 5: Write `src/components/ClaimSpan.tsx`

Create `studio/frontend/src/components/ClaimSpan.tsx`:

```typescript
import type { Claim, VerdictLabel } from "../types";
import "./App.css";

export function ClaimSpan({
  claim,
  label,
  onClick,
}: {
  claim: Claim;
  label: VerdictLabel;
  onClick: () => void;
}) {
  return (
    <span
      className={`claim claim-${label}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onClick();
      }}
    >
      {claim.text}
    </span>
  );
}
```

### Step 6: Write `src/components/EvidencePanel.tsx`

Create `studio/frontend/src/components/EvidencePanel.tsx`:

```typescript
import type { Verdict } from "../types";
import "./App.css";

export function EvidencePanel({
  verdict,
  onClose,
}: {
  verdict: Verdict;
  onClose: () => void;
}) {
  return (
    <aside className="evidence-panel" role="dialog" aria-label="Claim evidence">
      <header>
        <h2>Claim detail</h2>
        <button className="close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>
      <div className="meta">
        <div>
          label: <strong>{verdict.label}</strong>
        </div>
        <div>
          confidence: <strong>{verdict.confidence.toFixed(3)}</strong>
        </div>
        <div>
          tier: <strong>{verdict.tier}</strong>
        </div>
      </div>
      <h3>Claim</h3>
      <p>{verdict.claim.text}</p>
      <h3>Evidence</h3>
      {verdict.evidence ? (
        <>
          <div className="evidence-excerpt">{verdict.evidence.text}</div>
          <p>
            <small>source id: {verdict.evidence.source_id}</small>
          </p>
        </>
      ) : (
        <p className="no-evidence">No evidence available.</p>
      )}
    </aside>
  );
}
```

### Step 7: Run tests to verify they pass

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm test
```

Expected: 19 tests pass (13 from prior tasks + 8 new).

### Step 8: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/src/components/App.css studio/frontend/src/components/GateBadge.tsx studio/frontend/src/components/ClaimSpan.tsx studio/frontend/src/components/EvidencePanel.tsx studio/frontend/tests/GateBadge.test.tsx studio/frontend/tests/ClaimSpan.test.tsx studio/frontend/tests/EvidencePanel.test.tsx
git commit -m "studio frontend: GateBadge, ClaimSpan, EvidencePanel + tests

Three primitives that every page reuses:

  - GateBadge: small badge displaying the gate result (allowed/flagged/blocked)
  - ClaimSpan: clickable, verdict-colored claim text
  - EvidencePanel: side panel showing claim detail + evidence excerpt

Class names are the contract:
  .gate-badge.gate-{result}
  .claim.claim-{label}
  .evidence-panel

8 new tests cover class application, click handler, null evidence case."
```

---

## Task 7: RunResult component + tests

**Files:**
- Create: `studio/frontend/src/components/RunResult.tsx`
- Create: `studio/frontend/src/components/RunResult.css`
- Create: `studio/frontend/tests/RunResult.test.tsx`

**Why seventh**: the visible centerpiece of the acceptance demo. Walks the candidate answer, splits on claim spans, wraps each claim with a `ClaimSpan`.

**Interfaces:** `RunResult({ run: Run, onClaimClick: (verdict: Verdict) => void })` renders the gate badge, the candidate answer with claims highlighted, and the latency.

### Step 1: Write the failing test

Create `studio/frontend/tests/RunResult.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RunResult } from "../src/components/RunResult";
import type { Run } from "../src/types";

const run: Run = {
  id: "r1",
  project_id: "p1",
  question: "How long does shipping take?",
  model_or_prompt_label: "gpt-4",
  candidate_answer: "Shipping takes 1 to 2 days. Returns within 30 days.",
  source_document_versions: { d1: 1 },
  verdicts: [
    {
      claim: {
        id: "c1",
        text: "Shipping takes 1 to 2 days.",
        span: [0, 27],
      },
      label: "contradicted",
      confidence: 0.99,
      tier: "nli",
      evidence: {
        source_id: "d1",
        text: "3 to 5 business days.",
        span: [0, 22],
      },
      checked_at: "t",
    },
    {
      claim: {
        id: "c2",
        text: "Returns within 30 days.",
        span: [28, 50],
      },
      label: "entailed",
      confidence: 0.95,
      tier: "nli",
      evidence: null,
      checked_at: "t",
    },
  ],
  gate_result: "blocked",
  latency_ms: 642,
  created_at: "t",
};

describe("RunResult", () => {
  it("renders the gate badge with the right result", () => {
    render(<RunResult run={run} onClaimClick={() => {}} />);
    expect(screen.getByText("blocked")).toBeInTheDocument();
  });
  it("renders latency_ms formatted as ms", () => {
    render(<RunResult run={run} onClaimClick={() => {}} />);
    expect(screen.getByText(/642\s*ms/)).toBeInTheDocument();
  });
  it("renders both claim texts with the right verdict classes", () => {
    render(<RunResult run={run} onClaimClick={() => {}} />);
    expect(screen.getByText("Shipping takes 1 to 2 days.")).toHaveClass("claim-contradicted");
    expect(screen.getByText("Returns within 30 days.")).toHaveClass("claim-entailed");
  });
});
```

### Step 2: Run tests to verify they fail

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm test
```

Expected: RunResult tests fail with "Cannot find module".

### Step 3: Write `src/components/RunResult.css`

Create `studio/frontend/src/components/RunResult.css`:

```css
@import "../theme.css";

.run-result {
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-4);
}

.run-result header {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  margin-bottom: var(--space-4);
  font-size: 0.875rem;
  color: var(--color-muted);
}

.run-result .answer {
  font-size: 1.0625rem;
  line-height: 1.6;
  white-space: pre-wrap;
}
```

### Step 4: Write `src/components/RunResult.tsx`

Create `studio/frontend/src/components/RunResult.tsx`:

```typescript
import type { Run, Verdict } from "../types";
import { GateBadge } from "./GateBadge";
import { ClaimSpan } from "./ClaimSpan";
import "./RunResult.css";

export function RunResult({
  run,
  onClaimClick,
}: {
  run: Run;
  onClaimClick: (verdict: Verdict) => void;
}) {
  // Build segments from the candidate_answer + claim spans.
  // Each claim occupies [claim.span[0], claim.span[1]). Anything between
  // claims is plain text.
  const segments: Array<
    { kind: "text"; text: string } | { kind: "claim"; verdict: Verdict }
  > = [];

  const sorted = [...run.verdicts].sort(
    (a, b) => a.claim.span[0] - b.claim.span[0],
  );

  let cursor = 0;
  for (const v of sorted) {
    const [start, end] = v.claim.span;
    if (cursor < start) {
      segments.push({ kind: "text", text: run.candidate_answer.slice(cursor, start) });
    }
    segments.push({ kind: "claim", verdict: v });
    cursor = end;
  }
  if (cursor < run.candidate_answer.length) {
    segments.push({ kind: "text", text: run.candidate_answer.slice(cursor) });
  }

  return (
    <div className="run-result">
      <header>
        <GateBadge result={run.gate_result} />
        <span>verified in {run.latency_ms.toFixed(0)} ms</span>
        <span>model: {run.model_or_prompt_label}</span>
      </header>
      <div className="answer">
        {segments.map((seg, i) =>
          seg.kind === "text" ? (
            <span key={i}>{seg.text}</span>
          ) : (
            <ClaimSpan
              key={i}
              claim={seg.verdict.claim}
              label={seg.verdict.label}
              onClick={() => onClaimClick(seg.verdict)}
            />
          ),
        )}
      </div>
    </div>
  );
}
```

### Step 5: Run tests to verify they pass

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm test
```

Expected: 22 tests pass.

### Step 6: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/src/components/RunResult.tsx studio/frontend/src/components/RunResult.css studio/frontend/tests/RunResult.test.tsx
git commit -m "studio frontend: RunResult renders answer with color-coded claims

RunResult walks the candidate_answer, splits on claim.spans, and wraps
each claim in a ClaimSpan. Plain text between claims is preserved.

Header shows:
  - GateBadge (allowed/flagged/blocked)
  - latency_ms formatted as 'verified in 642 ms'
  - model_or_prompt_label

3 tests cover: gate badge rendering, latency formatting, verdict
classes on each claim."
```

---

## Task 8: Forms (ProjectForm, SourceDocForm, CheckForm) + tests

**Files:**
- Create: `studio/frontend/src/components/ProjectForm.tsx`
- Create: `studio/frontend/src/components/SourceDocForm.tsx`
- Create: `studio/frontend/src/components/CheckForm.tsx`
- Create: `studio/frontend/src/components/Forms.css`

**Why eighth**: forms are the data-entry side. They call mutations and surface loading/error states.

**Interfaces:**
- `ProjectForm({ onCreated: (project: Project) => void })` — name input + submit
- `SourceDocForm({ projectId: string, onCreated: (doc: SourceDocument) => void })` — name + content textarea + submit
- `CheckForm({ projectId: string, hasSourceDocs: boolean, onSubmitted: (run: Run) => void })` — question (optional), model label, candidate answer textarea + submit

### Step 1: Write `src/components/Forms.css`

Create `studio/frontend/src/components/Forms.css`:

```css
@import "../theme.css";

.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-4);
}

.form label {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: 0.875rem;
  font-weight: 500;
}

.form input[type="text"],
.form textarea {
  font-family: inherit;
  font-size: 1rem;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-bg);
  color: var(--color-fg);
}

.form textarea {
  resize: vertical;
  min-height: 6rem;
  font-family: var(--font-mono);
  font-size: 0.875rem;
  line-height: 1.5;
}

.form .actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.form button[type="submit"] {
  background: var(--color-accent);
  color: var(--color-accent-fg);
  font-weight: 600;
  padding: var(--space-2) var(--space-4);
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
}

.form button[type="submit"]:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form .error {
  color: var(--color-blocked-fg);
  background: var(--color-blocked-bg);
  border: 1px solid var(--color-blocked-border);
  border-radius: var(--radius);
  padding: var(--space-2) var(--space-3);
  font-size: 0.875rem;
}

.form .hint {
  color: var(--color-muted);
  font-size: 0.875rem;
}
```

### Step 2: Write `src/components/ProjectForm.tsx`

Create `studio/frontend/src/components/ProjectForm.tsx`:

```typescript
import { useState } from "react";
import { useCreateProject } from "../hooks/useStudioApi";
import type { Project } from "../types";
import "./Forms.css";

export function ProjectForm({ onCreated }: { onCreated: (p: Project) => void }) {
  const [name, setName] = useState("");
  const mutation = useCreateProject();

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim()) return;
        mutation.mutate(
          { name: name.trim() },
          { onSuccess: (p) => { onCreated(p); setName(""); } },
        );
      }}
    >
      <label>
        Project name
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. customer-support-kb"
          required
        />
      </label>
      <div className="actions">
        <button type="submit" disabled={mutation.isPending || !name.trim()}>
          {mutation.isPending ? "Creating…" : "Create project"}
        </button>
        {mutation.isError && (
          <span className="error">{(mutation.error as Error).message}</span>
        )}
      </div>
    </form>
  );
}
```

### Step 3: Write `src/components/SourceDocForm.tsx`

Create `studio/frontend/src/components/SourceDocForm.tsx`:

```typescript
import { useState } from "react";
import { useAddSourceDocument } from "../hooks/useStudioApi";
import type { SourceDocument } from "../types";
import "./Forms.css";

export function SourceDocForm({
  projectId,
  onCreated,
}: {
  projectId: string;
  onCreated: (doc: SourceDocument) => void;
}) {
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const mutation = useAddSourceDocument(projectId);

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!name.trim() || !content.trim()) return;
        mutation.mutate(
          { name: name.trim(), content },
          { onSuccess: (d) => { onCreated(d); setName(""); setContent(""); } },
        );
      }}
    >
      <label>
        Source name
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. shipping-faq"
          required
        />
      </label>
      <label>
        Source content
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Paste the source text here…"
          rows={8}
          required
        />
      </label>
      <div className="actions">
        <button
          type="submit"
          disabled={mutation.isPending || !name.trim() || !content.trim()}
        >
          {mutation.isPending ? "Adding…" : "Add source doc"}
        </button>
        {mutation.isError && (
          <span className="error">{(mutation.error as Error).message}</span>
        )}
      </div>
    </form>
  );
}
```

### Step 4: Write `src/components/CheckForm.tsx`

Create `studio/frontend/src/components/CheckForm.tsx`:

```typescript
import { useState } from "react";
import { useSubmitCheck } from "../hooks/useStudioApi";
import type { Run } from "../types";
import "./Forms.css";

export function CheckForm({
  projectId,
  hasSourceDocs,
  onSubmitted,
}: {
  projectId: string;
  hasSourceDocs: boolean;
  onSubmitted: (run: Run) => void;
}) {
  const [question, setQuestion] = useState("");
  const [label, setLabel] = useState("gpt-4");
  const [answer, setAnswer] = useState("");
  const mutation = useSubmitCheck(projectId);

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!label.trim() || !answer.trim()) return;
        mutation.mutate(
          {
            question: question.trim() || null,
            model_or_prompt_label: label.trim(),
            candidate_answer: answer,
          },
          { onSuccess: (r) => { onSubmitted(r); setAnswer(""); } },
        );
      }}
    >
      <label>
        Question (optional)
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. How long does shipping take?"
        />
      </label>
      <label>
        Model / prompt label
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          required
        />
      </label>
      <label>
        Candidate answer
        <textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          placeholder="Paste the candidate answer here…"
          rows={6}
          required
        />
      </label>
      <div className="actions">
        <button
          type="submit"
          disabled={mutation.isPending || !label.trim() || !answer.trim() || !hasSourceDocs}
        >
          {mutation.isPending ? "Verifying…" : "Submit check"}
        </button>
        {!hasSourceDocs && (
          <span className="hint">Add a source document first.</span>
        )}
        {mutation.isError && (
          <span className="error">{(mutation.error as Error).message}</span>
        )}
      </div>
    </form>
  );
}
```

### Step 5: Verify the build

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm run build
npm test
```

Expected: build succeeds, all 22 tests still pass.

### Step 6: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/src/components/ProjectForm.tsx studio/frontend/src/components/SourceDocForm.tsx studio/frontend/src/components/CheckForm.tsx studio/frontend/src/components/Forms.css
git commit -m "studio frontend: forms (ProjectForm, SourceDocForm, CheckForm)

Three forms that call the corresponding mutation hooks:

  - ProjectForm: name → createProject
  - SourceDocForm: name + content → addSourceDocument
  - CheckForm: question (optional) + label + answer → submitCheck

Each form:
  - Validates non-empty fields
  - Disables submit while pending
  - Shows error inline on failure
  - Calls onCreated/onSubmitted on success
  - Clears the input after success

CheckForm also guards against submitting with no source docs."
```

---

## Task 9: Lists (SourceDocList, RunHistory) + tests

**Files:**
- Create: `studio/frontend/src/components/SourceDocList.tsx`
- Create: `studio/frontend/src/components/RunHistory.tsx`
- Create: `studio/frontend/src/components/SourceDocItem.tsx` (small helper for edit)
- Create: `studio/frontend/src/components/Lists.css`

**Why ninth**: lists render the persisted state. They show version pinning and run history.

**Interfaces:**
- `SourceDocList({ projectId: string, onSelect?: (doc: SourceDocument) => void })` renders each source doc with version badge, edit button, content preview
- `RunHistory({ projectId: string, onSelect: (run: Run) => void })` renders each run chronologically with gate badge, label, latency, and source_document_versions

### Step 1: Write `src/components/Lists.css`

Create `studio/frontend/src/components/Lists.css`:

```css
@import "../theme.css";

.list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.list-item {
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-3);
}

.list-item header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: 0.875rem;
}

.list-item .name {
  font-weight: 600;
  flex: 1;
}

.list-item .version {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  background: var(--color-flagged-bg);
  color: var(--color-flagged-fg);
  padding: 0 0.4rem;
  border-radius: 3px;
}

.list-item .preview {
  margin-top: var(--space-2);
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--color-muted);
  max-height: 3rem;
  overflow: hidden;
  text-overflow: ellipsis;
}

.list-item .actions {
  margin-top: var(--space-2);
  display: flex;
  gap: var(--space-2);
}

.list-item button {
  font-size: 0.75rem;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-bg);
  cursor: pointer;
}

.list .empty {
  color: var(--color-muted);
  font-style: italic;
  text-align: center;
  padding: var(--space-4);
}
```

### Step 2: Write `src/components/SourceDocList.tsx`

Create `studio/frontend/src/components/SourceDocList.tsx`:

```typescript
import { useState } from "react";
import { useSourceDocuments, useUpdateSourceDocument } from "../hooks/useStudioApi";
import type { SourceDocument } from "../types";
import "./Lists.css";

export function SourceDocList({ projectId }: { projectId: string }) {
  const { data: docs, isLoading, isError, error } = useSourceDocuments(projectId);
  const [editing, setEditing] = useState<string | null>(null);

  if (isLoading) return <p className="empty">Loading source docs…</p>;
  if (isError) return <p className="empty">Error: {(error as Error).message}</p>;
  if (!docs || docs.length === 0) {
    return <p className="empty">No source documents yet. Add one above.</p>;
  }

  return (
    <div className="list">
      {docs.map((d) => (
        <SourceDocItem
          key={d.id}
          doc={d}
          isEditing={editing === d.id}
          onStartEdit={() => setEditing(d.id)}
          onCancelEdit={() => setEditing(null)}
        />
      ))}
    </div>
  );
}

function SourceDocItem({
  doc,
  isEditing,
  onStartEdit,
  onCancelEdit,
}: {
  doc: SourceDocument;
  isEditing: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
}) {
  const [content, setContent] = useState(doc.content);
  const update = useUpdateSourceDocument(doc.project_id, doc.id);

  if (isEditing) {
    return (
      <div className="list-item">
        <header>
          <span className="name">{doc.name}</span>
          <span className="version">v{doc.version}</span>
        </header>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={6}
          style={{ width: "100%", fontFamily: "var(--font-mono)" }}
        />
        <div className="actions">
          <button
            onClick={() =>
              update.mutate(
                { content },
                { onSuccess: () => onCancelEdit() },
              )
            }
            disabled={update.isPending || content === doc.content}
          >
            {update.isPending ? "Saving…" : "Save (bumps to v" + (doc.version + 1) + ")"}
          </button>
          <button onClick={onCancelEdit}>Cancel</button>
        </div>
        {update.isError && (
          <p className="error">{(update.error as Error).message}</p>
        )}
      </div>
    );
  }

  return (
    <div className="list-item">
      <header>
        <span className="name">{doc.name}</span>
        <span className="version">v{doc.version}</span>
      </header>
      <div className="preview">{doc.content.slice(0, 200)}…</div>
      <div className="actions">
        <button onClick={onStartEdit}>Edit (bumps version)</button>
      </div>
    </div>
  );
}
```

### Step 3: Write `src/components/RunHistory.tsx`

Create `studio/frontend/src/components/RunHistory.tsx`:

```typescript
import { useRuns } from "../hooks/useStudioApi";
import { GateBadge } from "./GateBadge";
import type { Run } from "../types";
import "./Lists.css";

export function RunHistory({
  projectId,
  onSelect,
}: {
  projectId: string;
  onSelect: (run: Run) => void;
}) {
  const { data: runs, isLoading, isError, error } = useRuns(projectId);

  if (isLoading) return <p className="empty">Loading runs…</p>;
  if (isError) return <p className="empty">Error: {(error as Error).message}</p>;
  if (!runs || runs.length === 0) {
    return <p className="empty">No runs yet. Submit your first check above.</p>;
  }

  return (
    <div className="list">
      {runs.map((r) => (
        <div
          key={r.id}
          className="list-item"
          onClick={() => onSelect(r)}
          role="button"
          tabIndex={0}
        >
          <header>
            <GateBadge result={r.gate_result} />
            <span className="name">{r.model_or_prompt_label}</span>
            <span className="version" style={{ fontFamily: "var(--font-mono)" }}>
              {r.latency_ms.toFixed(0)} ms
            </span>
          </header>
          <div className="preview">
            {r.candidate_answer.slice(0, 120)}…
          </div>
          <div className="preview" style={{ fontSize: "0.7rem" }}>
            pinned: {Object.entries(r.source_document_versions)
              .map(([id, v]) => `${id.slice(0, 6)}=v${v}`)
              .join(", ")}
          </div>
        </div>
      ))}
    </div>
  );
}
```

### Step 4: Verify the build

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm run build
npm test
```

Expected: build succeeds, all 22 tests still pass.

### Step 5: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/src/components/SourceDocList.tsx studio/frontend/src/components/RunHistory.tsx studio/frontend/src/components/Lists.css
git commit -m "studio frontend: SourceDocList + RunHistory

SourceDocList:
  - Lists current source docs with version badge
  - Edit button opens inline textarea, save bumps version (PATCH)
  - Content preview (first 200 chars)

RunHistory:
  - Lists runs chronologically (backend order)
  - Each row shows gate badge, model label, latency, content preview
  - Shows source_document_versions map (visible version pinning)
  - Click a row to load the run into the result panel"
```

---

## Task 10: Pages (ProjectList, ProjectDetail)

**Files:**
- Create: `studio/frontend/src/pages/ProjectList.tsx`
- Create: `studio/frontend/src/pages/ProjectDetail.tsx`
- Create: `studio/frontend/src/pages/Pages.css`

**Why tenth**: pages compose the previously-built components into the two views.

**Interfaces:**
- `ProjectList` — displays existing projects + ProjectForm to create new
- `ProjectDetail({ projectId: string })` — header, source docs (form + list), check form, run result panel, run history

### Step 1: Write `src/pages/Pages.css`

Create `studio/frontend/src/pages/Pages.css`:

```css
@import "../theme.css";

.page {
  max-width: 64rem;
  margin: 0 auto;
  padding: var(--space-8) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.page h1 {
  margin: 0;
  font-size: 1.75rem;
}

.page .section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.page .section h2 {
  margin: 0;
  font-size: 1.125rem;
  color: var(--color-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.project-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
  gap: var(--space-3);
}

.project-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: var(--space-4);
  text-decoration: none;
  color: var(--color-fg);
  transition: border-color 0.1s ease-in-out;
}

.project-card:hover {
  border-color: var(--color-accent);
}

.project-card .name {
  font-weight: 600;
  margin-bottom: var(--space-1);
}

.project-card .id {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--color-muted);
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--space-6);
}

@media (min-width: 60rem) {
  .detail-grid {
    grid-template-columns: 1fr 1fr;
  }
}
```

### Step 2: Write `src/pages/ProjectList.tsx`

Create `studio/frontend/src/pages/ProjectList.tsx`:

```typescript
import { Link } from "react-router-dom";
import { useProjects } from "../hooks/useStudioApi";
import { ProjectForm } from "../components/ProjectForm";
import "./Pages.css";

export function ProjectList() {
  const { data: projects, isLoading, isError, error } = useProjects();

  return (
    <div className="page">
      <h1>Elenchus Studio</h1>

      <section className="section">
        <h2>New project</h2>
        <ProjectForm onCreated={() => { /* query invalidated by hook */ }} />
      </section>

      <section className="section">
        <h2>Existing projects</h2>
        {isLoading && <p className="empty">Loading…</p>}
        {isError && <p className="error">{(error as Error).message}</p>}
        {projects && projects.length === 0 && (
          <p className="empty">No projects yet. Create one above.</p>
        )}
        {projects && projects.length > 0 && (
          <div className="project-list">
            {projects.map((p) => (
              <Link key={p.id} to={`/projects/${p.id}`} className="project-card">
                <div className="name">{p.name}</div>
                <div className="id">{p.id}</div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
```

### Step 3: Write `src/pages/ProjectDetail.tsx`

Create `studio/frontend/src/pages/ProjectDetail.tsx`:

```typescript
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useProject, useSourceDocuments } from "../hooks/useStudioApi";
import { SourceDocForm } from "../components/SourceDocForm";
import { SourceDocList } from "../components/SourceDocList";
import { CheckForm } from "../components/CheckForm";
import { RunResult } from "../components/RunResult";
import { EvidencePanel } from "../components/EvidencePanel";
import { RunHistory } from "../components/RunHistory";
import type { Run, Verdict } from "../types";
import "./Pages.css";

export function ProjectDetail() {
  const { projectId = "" } = useParams<{ projectId: string }>();
  const { data: project, isError: projectErr } = useProject(projectId);
  const { data: docs } = useSourceDocuments(projectId);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [selectedVerdict, setSelectedVerdict] = useState<Verdict | null>(null);

  if (projectErr) {
    return (
      <div className="page">
        <p>Project not found. <Link to="/">Go back</Link></p>
      </div>
    );
  }

  return (
    <div className="page">
      <header>
        <Link to="/">← Back</Link>
        <h1>{project?.name ?? "Loading…"}</h1>
      </header>

      <div className="detail-grid">
        <section className="section">
          <h2>Source documents</h2>
          <SourceDocForm projectId={projectId} onCreated={() => {}} />
          <SourceDocList projectId={projectId} />
        </section>

        <section className="section">
          <h2>Run a check</h2>
          <CheckForm
            projectId={projectId}
            hasSourceDocs={(docs?.length ?? 0) > 0}
            onSubmitted={(r) => setSelectedRun(r)}
          />
        </section>
      </div>

      {selectedRun && (
        <section className="section">
          <h2>Result</h2>
          <RunResult run={selectedRun} onClaimClick={setSelectedVerdict} />
        </section>
      )}

      <section className="section">
        <h2>Run history</h2>
        <RunHistory projectId={projectId} onSelect={setSelectedRun} />
      </section>

      {selectedVerdict && (
        <EvidencePanel
          verdict={selectedVerdict}
          onClose={() => setSelectedVerdict(null)}
        />
      )}
    </div>
  );
}
```

### Step 4: Verify the build

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm run build
npm test
```

Expected: build succeeds, all tests still pass.

### Step 5: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/src/pages/ProjectList.tsx studio/frontend/src/pages/ProjectDetail.tsx studio/frontend/src/pages/Pages.css
git commit -m "studio frontend: ProjectList + ProjectDetail pages

ProjectList:
  - Header
  - ProjectForm to create
  - Grid of existing projects (links)
  - Empty / loading / error states

ProjectDetail:
  - Header with project name + back link
  - Source docs section: form + list
  - Check form section
  - Result section (selectedRun)
  - Run history section (click a row to load)
  - Evidence panel (overlay) when a claim is clicked

Two-column grid on >=60rem screens, single column below."
```

---

## Task 11: App + routing + providers

**Files:**
- Modify: `studio/frontend/src/App.tsx`
- Modify: `studio/frontend/src/main.tsx`

**Why eleventh**: the wiring layer. Wraps the app in QueryClientProvider + BrowserRouter and defines routes.

**Interfaces:** none new — pure wiring.

### Step 1: Update `src/App.tsx`

Replace `studio/frontend/src/App.tsx` with:

```typescript
import { Routes, Route } from "react-router-dom";
import { ProjectList } from "./pages/ProjectList";
import { ProjectDetail } from "./pages/ProjectDetail";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ProjectList />} />
      <Route path="/projects/:projectId" element={<ProjectDetail />} />
    </Routes>
  );
}
```

### Step 2: Update `src/main.tsx`

Replace `studio/frontend/src/main.tsx` with:

```typescript
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: 1,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
```

### Step 3: Verify the build

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npm run build
npm test
```

Expected: build succeeds, all tests still pass.

### Step 4: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/src/App.tsx studio/frontend/src/main.tsx
git commit -m "studio frontend: App routing + QueryClientProvider wiring

  - BrowserRouter at the root
  - QueryClient with staleTime: 5s, retry: 1
  - Two routes: /   and   /projects/:projectId

This is the final wiring layer. The frontend already renders the
two pages from Task 10; this commit only adds the providers and routes."
```

---

## Task 12: Playwright E2E smoke test

**Files:**
- Create: `studio/frontend/playwright.config.ts`
- Create: `studio/frontend/e2e/studio_frontend_smoke.spec.ts`
- Create: `studio/frontend/e2e/global-setup.ts`
- Create: `studio/examples/studio_frontend_smoke_test.ts` (runner that boots FastAPI + NLI)

**Why twelfth**: the load-bearing acceptance test for Plan.md Phase 6 acceptance. Boots the real backend, builds the frontend, runs the visible-flow walk-through.

**Interfaces:** the spec file is a `test(...)` block; the runner starts a server subprocess.

### Step 1: Install Playwright browsers

```bash
cd /home/faqihhakim/Project/Elenchus/studio/frontend
npx playwright install chromium
```

Expected: Chromium is downloaded (~120MB).

### Step 2: Write `playwright.config.ts`

Create `studio/frontend/playwright.config.ts`:

```typescript
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    headless: true,
    baseURL: "http://localhost:8765",
  },
  reporter: "list",
});
```

### Step 3: Write the E2E spec

Create `studio/frontend/e2e/studio_frontend_smoke.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";

test("phase 6 acceptance: paste source, paste answer, see flagged claim", async ({
  page,
}) => {
  await page.goto("/");

  // Create a project.
  await page.getByLabel("Project name").fill("e2e-kb");
  await page.getByRole("button", { name: /create project/i }).click();
  await expect(page.getByText("e2e-kb")).toBeVisible();

  // Open the project.
  await page.getByText("e2e-kb").click();

  // Wait for the project page.
  await expect(page.getByRole("heading", { name: /e2e-kb/i })).toBeVisible();

  // Add a source doc.
  await page.getByLabel("Source name").fill("shipping-faq");
  await page.getByLabel("Source content").fill(
    "Standard shipping takes 3 to 5 business days within the continental United States.",
  );
  await page.getByRole("button", { name: /add source doc/i }).click();
  await expect(page.getByText("v1")).toBeVisible();

  // Submit a deliberately-wrong answer.
  await page.getByLabel("Candidate answer").fill(
    "Standard shipping takes 1 to 2 business days within the continental United States.",
  );
  await page.getByRole("button", { name: /submit check/i }).click();

  // The contradicted claim should appear with the right class.
  await expect(page.getByText("Standard shipping takes 1 to 2 business days within the continental United States."))
    .toHaveClass(/claim-contradicted/);

  // The gate badge should read "blocked".
  await expect(page.getByText("blocked").first()).toBeVisible();

  // Click the claim — evidence panel opens.
  await page.getByText("Standard shipping takes 1 to 2 business days within the continental United States.").click();
  await expect(page.getByText(/3 to 5 business days/i)).toBeVisible();

  // Close the panel.
  await page.getByRole("button", { name: /close/i }).click();

  // Run history shows the run.
  await expect(page.getByText("Run history")).toBeVisible();
});
```

### Step 4: Write the runner script

Create `studio/examples/studio_frontend_smoke_test.ts`:

```typescript
/**
 * Studio frontend E2E smoke test (Phase 6 acceptance).
 *
 * Boots the FastAPI server with the real NLI model, builds the React
 * frontend, runs the Playwright assertion script, and prints the result.
 * Exit 0 if all assertions pass, 1 otherwise.
 *
 * Usage (from the repo root):
 *
 *   cd studio/frontend && npm install && npx playwright install chromium
 *   cd ../.. && npm create --prefix studio/frontend vite@latest -- --template react-ts studio/frontend  # already done
 *   tsx studio/examples/studio_frontend_smoke_test.ts
 */
import { execSync, spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = 8765;
const dbPath = mkdtempSync(join(tmpdir(), "studio-e2e-")) + "/db.sqlite";

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForServer(url: string, timeoutMs: number) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(url);
      if (r.status < 500) return;
    } catch {
      // not yet
    }
    await sleep(500);
  }
  throw new Error(`server did not become ready at ${url} within ${timeoutMs}ms`);
}

async function main() {
  // 1. Build the frontend.
  console.log("[1/4] building frontend…");
  execSync("npm run build", {
    cwd: "studio/frontend",
    stdio: "inherit",
  });

  // 2. Start FastAPI with the built static files.
  console.log("[2/4] starting FastAPI server…");
  const server = spawn(
    "python",
    [
      "-m",
      "studio.api.server",
      "--db",
      dbPath,
      "--host",
      "127.0.0.1",
      "--port",
      String(PORT),
    ],
    {
      env: {
        ...process.env,
        LD_LIBRARY_PATH: (process.env.LD_LIBRARY_PATH ?? "") + ":" + `${process.env.HOME}/.local/lib`,
      },
      stdio: "inherit",
    },
  );

  try {
    await waitForServer(`http://127.0.0.1:${PORT}/api/projects`, 180_000);
    console.log("[3/4] server ready");

    // 3. Run the Playwright test.
    console.log("[4/4] running Playwright spec…");
    execSync("npx playwright test", {
      cwd: "studio/frontend",
      stdio: "inherit",
    });

    console.log("all acceptance checks passed");
  } finally {
    server.kill();
    rmSync(dbPath, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

### Step 5: Run the E2E test

```bash
cd /home/faqihhakim/Project/Elenchus
npx tsx studio/examples/studio_frontend_smoke_test.ts
```

Expected: prints each step, then `all acceptance checks passed`, exits 0.

If anything fails, the Playwright output will show which assertion failed (e.g. wrong class, missing text). Fix the offending component or test and re-run.

### Step 6: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/playwright.config.ts studio/frontend/e2e/studio_frontend_smoke.spec.ts studio/examples/studio_frontend_smoke_test.ts
git commit -m "studio frontend: playwright E2E smoke test (phase 6 acceptance)

The Phase 6 acceptance walk-through from Plan.md, automated:

  - open /; create a project named 'e2e-kb'; open it
  - paste source saying '3 to 5 business days'
  - paste candidate answer saying '1 to 2 business days'
  - assert the contradicted claim carries the .claim-contradicted class
  - assert the gate badge reads 'blocked'
  - click the claim; assert the evidence excerpt '3 to 5 business days' shows
  - close the panel; assert the run history shows the run

studio/examples/studio_frontend_smoke_test.ts is the runner: it
builds the frontend, starts FastAPI + the real NLI, runs the spec,
prints 'all acceptance checks passed' on success.

Honors Rule 9: this is the verified-evidence artifact for the
Phase 6 acceptance claim."
```

---

## Task 13: Documentation

**Files:**
- Create: `studio/frontend/README.md`
- Modify: `README.md` (Phase 6 status, frontend section)
- Modify: `studio/README.md` (frontend subsection)

**Why thirteenth**: document how to develop, build, and run the frontend.

### Step 1: Write `studio/frontend/README.md`

Create `studio/frontend/README.md`:

````markdown
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
````

### Step 2: Update the main `README.md`

In `/home/faqihhakim/Project/Elenchus/README.md`, change the Phase 6 line in the project-status table:

```markdown
- ✅ Phase 6: Studio frontend (React + TypeScript + Vite)
```

And in the "What's in here" section, add the Studio frontend subdirectory:

```markdown
studio/
├── api/                  FastAPI app + uvicorn entry point
├── db/                   StudioStore (Project, SourceDocument, Run, GatePolicy)
├── frontend/             Phase 6: React + TypeScript + Vite
├── gate.py               Output gate — pure function (Rule 2)
├── integrations/         Reserved for Phase 7 (Soteria/Lethe)
└── tests/                Gate + store + API tests
```

Add a "Studio frontend" section after the "Studio (Phase 5)" section:

```markdown
## Studio frontend (Phase 6)

`studio/frontend/` is a React + TypeScript + Vite SPA that consumes the
Phase 5 backend. It implements the Plan.md Phase 6 acceptance flow:
upload/paste a source document, paste a candidate answer, see the
verdicts color-coded with evidence on click, and view run history with
version pinning visible.

Run the dev server (hot reload):

```bash
# terminal 1 — backend
python -m studio.api.server --db /tmp/studio.sqlite --port 8765

# terminal 2 — frontend
cd studio/frontend
npm run dev
# open http://localhost:5173/
```

Build for production:

```bash
cd studio/frontend && npm run build
python -m studio.api.server --db /tmp/studio.sqlite --port 8765
# open http://localhost:8765/
```

The frontend never imports the `elenchus/` library directly (Rule 6).
It only talks to the backend over HTTP, exactly like an external client.
```

### Step 3: Update `studio/README.md`

At the end of `studio/README.md`, add a "Frontend" section:

```markdown
## Frontend (Phase 6)

See `studio/frontend/README.md` for the React + TypeScript + Vite
frontend. Briefly:

- `npm run dev` (with the FastAPI server running on :8765) gives hot reload at http://localhost:5173/.
- `npm run build` outputs `studio/frontend/dist/`, which the FastAPI server mounts at `/` when present.
- The frontend calls only `/api/*` paths. The API table at the top of this README lists those paths.
```

### Step 4: Commit

```bash
cd /home/faqihhakim/Project/Elenchus
git add studio/frontend/README.md README.md studio/README.md
git commit -m "docs: phase 6 studio frontend

  - studio/frontend/README.md: install, dev, build, test, layout
  - main README.md: update Phase 6 status; add Studio frontend section
  - studio/README.md: cross-link to frontend README

The acceptance flow is documented end-to-end: install → dev → build →
test → E2E. No new code, only docs."
```

---

## Self-review

**Spec coverage** (sections of the spec → tasks that implement them):

| Spec section | Task |
|---|---|
| Architecture (Vite + proxy + static mount) | 1, 2 |
| CORS | 1 |
| TS interfaces | 3 |
| theme.css | 3 |
| src/api.ts (12 typed wrappers) | 4 |
| src/hooks/useStudioApi.ts | 5 |
| GateBadge, ClaimSpan, EvidencePanel | 6 |
| RunResult (color-coded claims) | 7 |
| Forms (Project, SourceDoc, Check) | 8 |
| Lists (SourceDocList, RunHistory) | 9 |
| Pages (ProjectList, ProjectDetail) | 10 |
| App + routing + providers | 11 |
| Vitest component tests | 6, 7 |
| Mocked fetch tests | 4, 5 |
| Playwright E2E | 12 |
| Side-by-side comparison | explicitly deferred (not in plan) |
| Acceptance criteria (12-step walk) | 12 |
| Documentation | 13 |

**Placeholder scan**: every code block is concrete. No "TBD", "TODO", "fill in details".

**Type consistency**: the types in `src/types.ts` (Task 3) match the parameter types in `src/api.ts` (Task 4) and the hook signatures in `src/hooks/useStudioApi.ts` (Task 5). The component prop types match the types they consume (RunResult takes `Run`, EvidencePanel takes `Verdict`, etc.). The Pydantic URL paths in `studio/api/app.py` (Task 1) match the paths in `src/api.ts` (`/api/projects`, etc.).

**TDD discipline**: every component task (6, 7) writes tests first, runs them failing, then implements, then runs them passing. The API and hook tasks (4, 5) follow the same pattern.

**Single git identity**: every commit message instructs the engineer to commit as `fqih <fqihhakim@student.gunadarma.ac.id>` with no `Co-Authored-By:` trailer.

**Commit count**: this plan produces 13 commits across 13 tasks. Combined with the 1 spec commit and 1 design commit, Phase 6 contributes ~15 commits to the contribution history.
