# Elenchus Studio — backend API

Phase 5 deliverable. FastAPI service that wraps the Elenchus library
and adds project+source-document+run persistence, an output gate, and
version pinning so a verification run is reproducible against the exact
source snapshot it was originally checked against.

## Install

```bash
# from the repo root
pip install -e ".[studio]"
```

## Run the server

```bash
python -m studio.api.server --db /tmp/studio.sqlite --port 8765
```

The server loads the real cross-encoder NLI model on startup so the
`/checks` endpoint is hot. Subsequent checks take ~400–600ms on CPU.

If `studio/frontend/dist/` exists (run `npm run build` in `studio/frontend/`),
the FastAPI process also serves the React frontend at `/`. CORS is enabled
for the Vite dev server (`http://localhost:5173`). The 12 API endpoints live
under `/api/*`.

## Endpoints

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

## Output gate precedence

Per Schema.md, gate evaluation is deterministic and ordered:

1. `blocked` when `block_on_any_contradiction` is enabled and at least one
   verdict is `contradicted`.
2. `flagged` when `unverifiable_count > flag_if_unverifiable_count_exceeds`.
3. `allowed` otherwise.

That precedence is the **only** behavior in `studio/gate.py`. The gate
is a pure function over a Verdict list — no side effects, no logging,
no I/O. It is testable in isolation (see `studio/tests/test_gate.py`).

## Version pinning

Every `VerificationRun` records the `source_document_versions` map it
was checked against. When a run is created:

- The current version of each source document at the moment of the
  check is captured.
- The `(source_id, version)` pair is appended to the run.
- Verdicts are persisted verbatim.

Later edits to a source document bump its version (and add a new row
in the `source_documents` table). The old version is immutable, but
retrievable via `GET /api/projects/{id}/source-documents/{sid}?version=N`.

This is the load-bearing acceptance item from Plan.md Phase 5: a
previously-recorded run still points at the version it was actually
checked against, even after the source is edited.

## Run history

`GET /api/projects/{id}/runs` returns all runs for a project in
chronological order. Each run includes:

- `model_or_prompt_label` — the label to use for side-by-side
  comparison of two runs from different models or prompts.
- `source_document_versions` — the version snapshot.
- `verdicts` — the full per-claim verdicts with character-offset spans.
- `gate_result` — the policy decision at the time of the run.
- `latency_ms` — wall-clock latency of the verification call.
- `created_at` — server-side timestamp.

The history is the comparison substrate the Phase 6 frontend will
render.

## Run the E2E smoke test

```bash
LD_LIBRARY_PATH=$HOME/.local/lib python -m studio.examples.studio_smoke_test
```

This walks the Plan.md Phase 5 acceptance end-to-end against a fresh
SQLite DB, using the real NLI model. It exits 0 if all expectations
pass, 1 otherwise, and prints the full HTTP exchange to stdout.

## Phase 7 (Soteria + Lethe) — opt-in

Phase 7 is **off by default**. A project opts in by setting
`phase7_enabled=true` on its gate policy:

```bash
curl -X PUT http://localhost:8765/api/projects/$PID/gate-policy \
  -H 'content-type: application/json' \
  -d '{"block_on_any_contradiction": true,
       "flag_if_unverifiable_count_exceeds": 1,
       "phase7_enabled": true}'
```

When enabled, `POST /api/projects/{id}/checks` triggers Phase 7
integrations per the gate result, post-persist:

| Gate result | Integration | Persisted on run row |
|-------------|-------------|----------------------|
| `blocked`   | Soteria retry loop (bounded by `max_steps`, `max_runtime_seconds`, `repeated_action_limit`, `consecutive_error_limit`) | `phase7_retry_attempts`, `phase7_retry_stop_reason` |
| `allowed`   | Lethe per-project memory: one `MemoryItem` per `supported` verdict, tagged with `run:{run_id}` | `phase7_memory_item_ids` (list of memory ids) |
| `flagged`   | Neither (skipped) | — |

Install:

```bash
pip install -e ".[phase7]"   # adds soteria-loop + lethe-agent (editable)
```

Per-project Lethe SQLite lives at `<studio_db_dir>/phase7/<project_id>.sqlite`.
This means each project's memory is isolated — there is no cross-project leak
and no global directory to clean up.

Behavior when a Phase 7 dependency is missing:

- A `blocked` run with Soteria missing → **HTTP 503** with a message
  naming `soteria-loop`.
- An `allowed` run with Lethe missing → **HTTP 503** with a message
  naming `lethe-agent`.

Behavior on Phase 7 runtime errors (other than missing-dep): the error
is **soft-failed** — the run row records the partial state
(`phase7_retry_stop_reason="error"`, `phase7_memory_item_ids=[]`),
and the gate result is unchanged. Phase 7 is never load-bearing for the
gate decision.

Walk the Phase 7 acceptance end-to-end:

```bash
LD_LIBRARY_PATH=$HOME/.local/lib python -m studio.examples.studio_phase7_smoke_test
```

This is the same boot pattern as `studio_smoke_test.py` (subprocess +
httpx + `_wait_ready`); it adds Phase 7 expectations on top.

## Phase 7 design notes

- **Lazy imports.** `studio/integrations/__init__.py` does NOT import
  `soteria-loop` or `lethe-agent` at module load. The adapters are
  loaded on first call so `pip install -e ".[studio]"` works without
  `.[phase7]`.
- **`Phase7DependencyError`.** Raised by the adapters when the
  underlying library is not importable. The handler maps it to HTTP
  503.
- **`RetryResult`** (returned by `run_retry`): dataclass with `attempts`
  (int) and `stop_reason` (str) — `closed` Soteria `StopReason` values
  are mapped to their `value` strings so they survive JSON.
- **Per-project memory.** The Lethe adapter opens one SQLite backend
  per project and `lru_cache`s it (`maxsize=64`); multiple sequential
  writes in one process reuse the same file handle.
- **Soft-fail vs hard-fail.** Only missing-dep is hard (503). Anything
  else during a Phase 7 integration is soft — the run is recorded
  with the partial result and the gate decision stands.
- **Tags.** Each Lethe `MemoryItem` carries
  `["elenchus_verified", "run:{run_id}", "project:{project_id}",
  "source:{source_id}", "v{version}"]` so a later `recall_run_claims`
  call filters cleanly.

## Tests

```bash
LD_LIBRARY_PATH=$HOME/.local/lib python -m pytest studio/tests
```

68 tests across the gate (11), store (20), API (19), Phase 7 schema (5),
Phase 7 soteria (4), Phase 7 lethe (5), and Phase 7 API (4).

## Rules walkthrough

| Rule | How it was honored |
|------|--------------------|
| **1** | The store keeps every tunable the API exposes (gate policy). The Verifier's `VerificationConfig` is unchanged and still the single source of truth for library-level tunables. |
| **2** | Gate policy is configuration, stored per project in `project_gate_policies`, returned as the default when unset. The gate itself is a pure function; the API just round-trips config. |
| **3** | The gate defaults to `unverifiable` when no judge is configured — already enforced by the library; the Studio carries that behavior forward. |
| **4** | Every check appends a `verification_log` entry through the standard `elenchus.verification_log` API, and the run is persisted with its verdicts as JSON. |
| **5** | The check endpoint uses the public `Verifier.verify(...)` from the library — the same code path the CLI uses. (Streaming is library-level, not yet exposed via API.) |
| **6** | `studio/` (excluding `studio/integrations/`) does not import `soteria` or `lethe`. The Phase 7 adapters live exclusively under `studio/integrations/`. The API handler imports the package and calls module-level proxies (`_phase7.run_retry(...)`), so missing-dep surfaces as `Phase7DependencyError` → 503 instead of an `ImportError` at startup. |
| **7** | Every call into the library goes through the public API (`Verifier`, `VerificationConfig`, `NliVerifier`). Private helpers are not used. Phase 7 touches Verifier only via its public `.verify(...)` surface. |
| **8** | Doesn't touch benchmarks. N/A. |
| **9** | Stopping here for review. |
| **10** | Smoke tests report real latency and real NLI confidence scores. No smoothing. |

## Frontend (Phase 6)

See `studio/frontend/README.md` for the React + TypeScript + Vite
frontend. Briefly:

- `npm run dev` (with the FastAPI server running on :8765) gives hot reload at http://localhost:5173/.
- `npm run build` outputs `studio/frontend/dist/`, which the FastAPI server mounts at `/` when present.
- The frontend calls only `/api/*` paths. The API table at the top of this README lists those paths.
