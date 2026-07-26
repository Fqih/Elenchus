# Elenchus Studio — Frontend Design (Phase 6)

**Status**: Proposed for approval
**Date**: 2026-07-26
**Author**: fqih
**Phase**: 6 of 7 (per `.context/Plan.md`)

## Purpose

Add a minimal web UI to Elenchus Studio so that a person with no prior context
can upload a source document, paste an answer with one deliberately false claim,
and correctly identify which claim was flagged and why — using only the UI, no
reading API responses directly.

## Scope

In scope (v1):

- Project list + create
- Project detail: source documents (paste/add), check submission, run history
- Color-coded claims with evidence on click
- Run history with version pinning visible

Deferred (v1.5 / Phase 6.5):

- Side-by-side comparison view of multiple runs

Out of scope (per Plan.md):

- Candidate generation (no LLM call from the frontend)
- Auth, multi-tenancy, hosting (per Design.md)

## Constraints

- Rule 7: frontend is a consumer of the library, not a special case. It calls
  the public FastAPI endpoints exactly like any external client — no private
  internals.
- Rule 6: frontend does not import `elenchus/` directly. It only talks to the
  backend over HTTP.
- Design.md: local, single-user, no auth. CORS in dev only.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Browser (React, TypeScript)                                   │
│  ────────────────────────────                                   │
│  Vite dev (:5173)                prod: build → dist/          │
│  proxies /api → :8765            served by FastAPI StaticFiles │
└────────────────┬───────────────────────────────────────────────┘
                 │  /api/* (proxied in dev, same-origin in prod)
                 ▼
┌────────────────────────────────────────────────────────────────┐
│  FastAPI (uvicorn, :8765)                                      │
│  ────────────────────────                                       │
│  studio/api/app.py  — 12 endpoints (Phase 5, unchanged)        │
│  mounts NLI on startup       serves studio/frontend/dist/      │
│  SQLite store (/tmp/studio.sqlite)                             │
└────────────────┬───────────────────────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────────────────────┐
│  Elenchus library (Verifier, VerificationConfig, GatePolicy)   │
│  — unchanged from Phase 5 — Rule 7 honored                     │
└────────────────────────────────────────────────────────────────┘
```

### Two scripts

- `npm run dev` — Vite dev server, hot reload, proxies `/api` to `:8765`
- `npm run build` — outputs `studio/frontend/dist/`, mounted by FastAPI in prod

## Components

### File layout

```
studio/frontend/
├── package.json              vite, react, react-router, @tanstack/react-query
├── tsconfig.json             Vite defaults
├── vite.config.ts            proxy /api → :8765
├── index.html                Vite entry
├── src/
│   ├── main.tsx              React root, QueryClientProvider, BrowserRouter
│   ├── api.ts                typed fetch wrappers per endpoint (12 fns)
│   ├── types.ts              TS interfaces mirroring Pydantic models
│   ├── theme.css             color variables
│   ├── App.tsx               routes
│   ├── pages/
│   │   ├── ProjectList.tsx   /
│   │   └── ProjectDetail.tsx /projects/:id
│   ├── components/
│   │   ├── ProjectForm.tsx
│   │   ├── SourceDocForm.tsx
│   │   ├── SourceDocList.tsx
│   │   ├── CheckForm.tsx
│   │   ├── RunResult.tsx
│   │   ├── ClaimSpan.tsx
│   │   ├── EvidencePanel.tsx
│   │   ├── RunHistory.tsx
│   │   └── GateBadge.tsx
│   └── hooks/
│       └── useStudioApi.ts    TanStack Query hooks per endpoint
└── tests/
    ├── api.test.ts
    ├── ClaimSpan.test.tsx
    ├── GateBadge.test.tsx
    └── RunResult.test.tsx
```

### TypeScript interfaces

```typescript
export type VerdictLabel = "entailed" | "contradicted" | "unverifiable";
export type GateResult = "allowed" | "flagged" | "blocked";

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
  tier: "nli" | "judge";
  evidence: Evidence | null;
  checked_at: string;
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

export interface Project {
  id: string;
  name: string;
  created_at: string;
}
```

These are hand-typed from the Pydantic models in `studio/api/app.py:43-103`.
No codegen — 12 endpoints is cheap to maintain.

### Color theme

`theme.css` exposes:

- `--color-allowed`: green
- `--color-flagged`: amber
- `--color-blocked`: red
- `--color-bg`, `--color-fg`, `--color-muted`: layout
- `--color-accent`: links/buttons

Plain readable colors, no design system.

## Data flow

### User journey

1. **Open `/projects/:id`** — three queries in parallel:
   - `GET /projects/:id`
   - `GET /projects/:id/source-documents`
   - `GET /projects/:id/runs`
   - Spinner until done.

2. **Paste source doc, click "Add"** —
   `POST /projects/:id/source-documents`,
   invalidate `['source-docs', id]` on success.

3. **Paste candidate answer, click "Submit check"** —
   `POST /projects/:id/checks`,
   button shows spinner + "Verifying…" (real NLI: ~500ms–1s),
   on success: render `<RunResult>` with the new run, invalidate `['runs', id]`.

4. **See answer with claims color-coded** — `RunResult` walks
   `candidate_answer`, splits on `claim.span`, wraps each in
   `<ClaimSpan label={v.label}>` with the verdict class.
   - `contradicted` → red
   - `unverifiable` → amber
   - `entailed` → plain (or faint green)
   - Gate badge at top: `blocked` / `flagged` / `allowed`
   - `latency_ms` shown next to badge ("verified in 642ms")

5. **Click a contradicted claim** — `ClaimSpan.onClick` sets
   `selectedClaim`; `EvidencePanel` slides in showing claim text, label,
   confidence, tier, evidence span text, source_id (clickable link to
   source doc).

6. **Edit source doc → version bumps** — `PATCH` response carries new
   `version`. List shows v1 as "previous version" link. Re-running a check
   records `source_document_versions={sid:2}`. Existing runs in history
   still pin to v1 (visible in run detail).

### State management

- **Server state** (projects, source docs, runs, gate policy) →
  TanStack Query
- **Local state** (selected claim, modal open, form drafts) → `useState`
- **No global state library** (Redux/Zustand) — not needed for this scope

### Loading states

- Page-level: `<Spinner />` while `isLoading`
- Mutation: button disabled + spinner inside button
- Background refetch: subtle indicator (TanStack Query built-in)

## Error handling

| Failure | UX | Code path |
|---|---|---|
| Network down / server unreachable | Toast: "Cannot reach Studio server. Is it running on port 8765?" | TanStack Query `onError` |
| 404 (project / source / run missing) | Inline: "Project not found. Go back to project list" | Component-level `isError` |
| 400 (form validation) | Inline form error, field highlighted | `await r.json()` → `detail` |
| 500 (NLI model broken, SQLite locked) | Toast: "Studio server error: <detail>" with retry button | TanStack Query `onError` |
| Check takes too long (>30s) | Spinner → "still verifying…" — no auto-retry | `useMutation` timeout |
| Empty source docs at check time | Submit disabled, hint: "Add a source document first" | `source-docs.length === 0` guard |
| Hallucinated answer → run is `blocked` | Red badge + contradicted claim highlighted louder | `<GateBadge variant="blocked">` |
| Run history empty | "No runs yet. Submit your first check above." | `runs.length === 0` |

### Implementation

A single `apiCall<T>(path, init): Promise<T>` wrapper in `api.ts`:

- Throws if `!response.ok` with `{ status, detail }`
- Returns parsed JSON

Each `useQuery` / `useMutation` hook catches the error and lets the
component handle it. **No silent swallowed errors.**

### Strict mode

React 18 strict mode enabled in dev (catches double-fetch bugs).

### CORS

FastAPI configured to allow `http://localhost:5173` (Vite dev) and
same-origin in prod.

## Testing

### Layer 1 — Component unit tests (Vitest + React Testing Library)

Per-component, focus on visible behavior (test ID, text, class names):

```typescript
// ClaimSpan.test.tsx
test("renders claim with correct class for contradicted label", () => {
  render(<ClaimSpan claim={claim} verdict={contradicted} onClick={noop} />);
  expect(screen.getByText(claim.text)).toHaveClass("verdict-contradicted");
});

// GateBadge.test.tsx
test("applies blocked-class for blocked gate result", () => {
  render(<GateBadge result="blocked" />);
  expect(screen.getByText("blocked")).toHaveClass("gate-blocked");
});

// RunResult.test.tsx
test("renders candidate answer with claims in order", () => {
  const answer = "First claim. Second claim with a lie.";
  const verdicts = [...];
  render(<RunResult candidate_answer={answer} verdicts={verdicts} />);
  // both claims rendered, second has different class
});
```

### Layer 2 — API wrapper tests (Vitest, `fetch` mocked)

```typescript
// api.test.ts
test("createProject POSTs name and returns Project", async () => {
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve(new Response(JSON.stringify({id: "p1", name: "kb", created_at: "..."}), {status: 200}))
  ));
  const p = await createProject({name: "kb"});
  expect(p.id).toBe("p1");
  expect(fetch).toHaveBeenCalledWith("/api/projects", expect.objectContaining({method: "POST"}));
});

test("submitCheck throws on 4xx with parsed detail", async () => {
  vi.stubGlobal("fetch", vi.fn(() =>
    Promise.resolve(new Response(JSON.stringify({detail: "project not found"}), {status: 404}))
  ));
  await expect(submitCheck("p1", req)).rejects.toThrow("project not found");
});
```

### Layer 3 — E2E smoke test (Playwright, real backend)

A new `studio/examples/studio_frontend_smoke_test.ts` that:

1. Starts FastAPI + NLI on a free port
2. Runs `npm run build`, mounts the static `dist/`
3. Launches headless Chromium, navigates to the running app
4. Walks the full acceptance flow visually:
   - Create project
   - Add source doc with a paragraph saying "Standard shipping takes 3 to 5 business days"
   - Submit a check with "Standard shipping takes 1 to 2 business days"
   - Visually verify the contradicted claim is highlighted red
   - Click it, visually verify the evidence excerpt is shown
   - Open history, verify the run appears
5. Exit 0 if all visual checks pass, 1 otherwise

The existing `studio/examples/studio_smoke_test.py` (HTTP-only) covers the
API surface. The new one covers the UI acceptance.

### Why Playwright, not Cypress

- Single npm dep
- Faster, better TS support
- Runs HTTP + headless browser in one process

## Acceptance criteria (per Plan.md Phase 6)

A person with no prior context can upload a source document, paste an answer
with one deliberately false claim, and correctly identify which claim was
flagged and why, using only the UI — no reading API responses directly.

**Concrete walk-through**:

1. Open browser to `http://localhost:8765/`
2. Create a project called "kb"
3. Paste source: "Standard shipping takes 3 to 5 business days…"
4. Submit answer: "Standard shipping takes 1 to 2 business days…"
5. See the contradicted claim visually red-highlighted
6. Click the claim
7. See the evidence excerpt showing the source's "3 to 5 business days"
8. Open history; see the run with `gate_result: blocked` and `latency_ms: ~500`
9. Edit source doc to say "7 to 10 business days"
10. Submit the same hallucinated answer again
11. See the run still pin to v1 in history (version badge)
12. Open the new run — confirm it pins to v2 of the source doc. (Side-by-side
    comparison is deferred to v1.5; the version-pinning difference is visible
    in each run's `source_document_versions` map.)

## Risks / non-goals

- **First NLI load is slow** (~30s once on first cold start). The smoke test
  budgets for this via `_wait_ready`. UI does not need to know.
- **No auth**. Anyone with localhost access has full access. Per Design.md,
  this is intentional.
- **No codegen for TS types**. If a Pydantic field changes, the TS interface
  must be updated by hand. The risk is bounded by the 12-endpoint surface.
- **No offline mode**. Server must be running.

## What comes next

- Phase 7: Soteria + Lethe integration, per `.context/Plan.md`. Inputs
  (`Loopward/`, `Lethe/`) are present locally. Not addressed by this spec.
