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

## Endpoints

| Method | Path                                                       | Purpose |
|-------:|------------------------------------------------------------|---------|
| POST   | `/projects`                                                | Create a project |
| GET    | `/projects`                                                | List projects |
| GET    | `/projects/{project_id}`                                   | Get a project |
| POST   | `/projects/{project_id}/source-documents`                  | Add a source document (gets v1) |
| GET    | `/projects/{project_id}/source-documents`                  | List current source documents |
| GET    | `/projects/{project_id}/source-documents/{sid}`            | Get a source document (latest by default, `?version=N` for older) |
| PATCH  | `/projects/{project_id}/source-documents/{sid}`            | Edit a source document (bumps version) |
| POST   | `/projects/{project_id}/checks`                            | Submit a check (runs the library + output gate) |
| GET    | `/projects/{project_id}/runs`                              | List run history (chronological order) |
| GET    | `/runs/{run_id}`                                           | Get a single run including its verdicts |
| GET    | `/projects/{project_id}/gate-policy`                       | Get the project's output-gate policy |
| PUT    | `/projects/{project_id}/gate-policy`                       | Set the project's output-gate policy |

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
retrievable via `GET /projects/{id}/source-documents/{sid}?version=N`.

This is the load-bearing acceptance item from Plan.md Phase 5: a
previously-recorded run still points at the version it was actually
checked against, even after the source is edited.

## Run history

`GET /projects/{id}/runs` returns all runs for a project in
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

## Tests

```bash
LD_LIBRARY_PATH=$HOME/.local/lib python -m pytest studio/tests
```

50 tests across the gate (11), store (20), and API (19).

## Rules walkthrough (Phase 5)

| Rule | How it was honored |
|------|--------------------|
| **1** | The store keeps every tunable the API exposes (gate policy). The Verifier's `VerificationConfig` is unchanged and still the single source of truth for library-level tunables. |
| **2** | Gate policy is configuration, stored per project in `project_gate_policies`, returned as the default when unset. The gate itself is a pure function; the API just round-trips config. |
| **3** | The gate defaults to `unverifiable` when no judge is configured — already enforced by the library; the Studio carries that behavior forward. |
| **4** | Every check appends a `verification_log` entry through the standard `elenchus.verification_log` API, and the run is persisted with its verdicts as JSON. |
| **5** | The check endpoint uses the public `Verifier.verify(...)` from the library — the same code path the CLI uses. (Streaming is library-level, not yet exposed via API.) |
| **6** | `studio/` does not import `soteria` or `lethe`. The `studio/integrations/` directory is empty and reserved for Phase 7. |
| **7** | Every call into the library goes through the public API (`Verifier`, `VerificationConfig`, `NliVerifier`). Private helpers are not used. |
| **8** | Phase 5 doesn't touch benchmarks. N/A. |
| **9** | Stopping here for review. |
| **10** | The smoke test reports the real latency (~500ms per check on CPU) and the actual NLI confidence scores. No smoothing. |
