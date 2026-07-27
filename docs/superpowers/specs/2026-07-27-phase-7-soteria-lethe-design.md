# Phase 7 — Soteria + Lethe Integration (Studio Backend)

> **Spec for:** Elenchus Studio backend wiring of the Soteria runtime and Lethe
> memory layer, per `.context/Plan.md` Phase 7.
>
> **Status:** design — pending approval before plan/implementation.

## Goal

Wire the Studio backend's output gate so that:

- **Blocked runs** trigger a bounded, observable Soteria retry loop (not an
  infinite loop, not a silent failure).
- **Allowed runs** write the supported claims (and only those) into a Lethe
  `MemoryStore`, each claim traceable back to its verification run id.

Both integrations live in `studio/integrations/`. The `elenchus/` library
stays untouched (Rule 6). The integrations are gated per-project via a
new `phase7_enabled` field on the gate policy.

## Non-goals

- Candidate generation in Studio (Rule 4). Soteria's runtime wraps the
  existing `Verifier` as its single tool; the agent loop does not generate
  text — it only re-invokes the verifier.
- Cross-project memory sharing. Each project gets its own Lethe SQLite
  backend; no global namespace.
- A separate retry worker process. Retries run in-process inside the
  `/checks` handler; v1 is single-process uvicorn.
- Side-by-side comparison UI for Phase 7 (deferred per Phase 6 plan).

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Studio FastAPI  (POST /api/projects/{id}/checks)            │
│                                                             │
│  1. Existing: Verifier.verify → evaluate_gate               │
│  2. NEW: if phase7_enabled AND gate_result == "blocked":    │
│       → studio.integrations.soteria.run_retry(...)          │
│  3. NEW: if phase7_enabled AND gate_result == "allowed":    │
│       → studio.integrations.lethe.write_supported_claims(   │
│           project_id, run_id, verdicts, source_versions)    │
│  4. Existing: persist Run + new Phase 7 columns             │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┴────────────────────┐
        ▼                                        ▼
┌──────────────────────────┐      ┌──────────────────────────────┐
│ studio/integrations/     │      │ studio/integrations/         │
│   soteria.py             │      │   lethe.py                   │
│                          │      │                              │
│ - Soteria AgentRuntime   │      │ - one MemoryItem per         │
│   with verifier as its   │      │   entailed verdict           │
│   only tool              │      │ - per-project SQLite at      │
│ - LoopPolicy:            │      │   <db_dir>/phase7/           │
│   repeated_action_limit=2│      │   {project_id}.sqlite        │
│   max_total_steps=4      │      │ - rich metadata + tags       │
│   max_runtime_seconds=30 │      │   for run_id traceability    │
│ - returns:               │      │ - default HashFakeEmbedder   │
│   attempts, stop_reason, │      │   (no sentence-transformers  │
│   final_verdicts         │      │   dependency for v1)         │
└──────────────────────────┘      └──────────────────────────────┘
```

## Components

### `studio/integrations/soteria.py`

```python
@dataclass
class RetryResult:
    attempts: int
    stop_reason: str            # Soteria StopReason enum value as str
    final_verdicts: list[Verdict]

def run_retry(
    verifier: Verifier,
    config: VerificationConfig,
    *,
    candidate_answer: str,
    source_documents: list[tuple[str, str]],   # (source_id, content)
    candidate_question: Optional[str],
    max_attempts: int = 2,
) -> RetryResult: ...
```

- Builds an `AgentRuntime` whose sole tool is `verify_candidate` (wraps the
  existing `verifier.verify(...)` call).
- Uses Soteria's `FakeProvider` because Rule 4 forbids candidate generation;
  the agent's only action is to re-invoke the verifier with identical args.
- LoopPolicy bounds:
  - `repeated_action_limit = max_attempts` — exits with `REPEATED_ACTION`
    when the same tool is called `max_attempts` times.
  - `max_total_steps = max_attempts + 1` — final ceiling.
  - `max_runtime_seconds = 30.0` — wall-clock cap.
- Event store: Soteria's `InMemoryEventStore` (no per-retry persistence; the
  attempt count + StopReason are the only state we propagate to the Run row).

### `studio/integrations/lethe.py`

```python
def write_supported_claims(
    *,
    project_id: str,
    run_id: str,
    verdicts: list[Verdict],
    source_versions: dict[str, int],     # {source_id: version}
) -> list[str]:
    """Return memory_ids in input order. Only writes verdicts with label == entailed."""

def recall_run_claims(project_id: str, run_id: str) -> list[MemoryItem]:
    """Return the MemoryItems written for run_id (debug/UI hook)."""
```

- One MemoryItem per `entailed` verdict. `contradicted` and `unverifiable`
  verdicts are NOT written (Plan.md: "exactly the supported claims and only
  those").
- Per-item payload:
  - `content` = `verdict.claim.text`
  - `session_id` = `project_id`
  - `tags` = `["elenchus_verified", f"run:{run_id}"]`
  - `metadata` = `{"run_id": run_id, "project_id": project_id,
    "source_id": evidence.source_id, "version": source_versions[source_id],
    "label": verdict.label.value, "confidence": verdict.confidence}`
- Backend: Lethe `SQLiteBackend` at `<db_dir>/phase7/{project_id}.sqlite`,
  opened lazily per process and cached in a process-local dict keyed by
  `project_id`.
- Embedder: Lethe's bundled `HashFakeEmbedder` (no `sentence-transformers`
  dependency for v1).
- `recall_run_claims` filters the project's SQLite by
  `tags LIKE '%run:{run_id}%'` (Lethe's `SQLiteBackend` supports `where=`).

### `studio/integrations/__init__.py`

Re-exports `run_retry`, `RetryResult`, `write_supported_claims`,
`recall_run_claims`. Lazy-imports `soteria_loop` and `lethe` so the Studio
server still starts when Phase 7 deps are missing; raises
`Phase7DependencyError` only on first retry/write attempt.

## Schema changes

### `project_gate_policies` (extend)

```sql
ALTER TABLE project_gate_policies ADD COLUMN phase7_enabled INTEGER NOT NULL DEFAULT 0;
```

- Default `False` — existing projects don't suddenly start invoking Soteria
  or writing to Lethe after upgrade.
- Lives in the gate policy because it's a per-project toggle that controls
  flow (Rules 1, 2).

### `runs` (extend)

```sql
ALTER TABLE runs ADD COLUMN phase7_retry_stop_reason TEXT;
ALTER TABLE runs ADD COLUMN phase7_retry_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN phase7_memory_item_ids TEXT NOT NULL DEFAULT '[]';
```

- `phase7_retry_stop_reason`: Soteria StopReason as string, non-null only
  if a retry ran.
- `phase7_retry_attempts`: integer count of verifier invocations inside
  the Soteria loop. 0 when no retry ran (gate != blocked, or toggle off,
  or flagged).
- `phase7_memory_item_ids`: JSON list of Lethe memory_ids; traceable per
  claim back to this run_id.

### Migration

`_migrate_phase7_columns(conn)` in `studio/db/store.py` — idempotent
(`PRAGMA table_info` check + `ALTER TABLE` only when column missing).
Phase 5's existing migration path stays untouched.

### `CheckResponse` (extend, `studio/api/app.py`)

```python
phase7_retry_stop_reason: Optional[str] = None
phase7_retry_attempts: int = 0
phase7_memory_item_ids: List[str] = []
```

Frontend ignores for v1; populated server-side.

## Wiring into `/checks`

```python
@app.post("/api/projects/{project_id}/checks")
def submit_check(project_id: str, req: SubmitCheckRequest) -> CheckResponse:
    # ... existing: load project, snapshot source docs by version,
    #     verifier.verify, evaluate_gate ...

    phase7_enabled = gate_policy.phase7_enabled
    retry_stop_reason: Optional[str] = None
    retry_attempts: int = 0
    memory_item_ids: list[str] = []

    if phase7_enabled and gate_result == "blocked":
        retry = soteria.run_retry(
            verifier=verifier, config=config,
            candidate_answer=req.candidate_answer,
            source_documents=[(sid, content) for sid, content in source_docs],
            candidate_question=req.question,
            max_attempts=int(os.environ.get("ELENCHUS_PHASE7_MAX_ATTEMPTS", "2")),
        )
        retry_stop_reason = retry.stop_reason
        retry_attempts = retry.attempts
        # gate_result is NOT overwritten: Plan.md says "triggers a bounded retry",
        # not "changes the gate outcome".

    elif phase7_enabled and gate_result == "allowed":
        memory_item_ids = lethe.write_supported_claims(
            project_id=project_id, run_id=run_id,
            verdicts=verdicts, source_versions=source_versions,
        )

    # flagged: skip both (no retry, no memory)

    # ... existing persist-Run, plus new columns ...
```

The run_id is generated up-front (UUID) so the Lethe memory items can
reference it before the Run row is persisted. Memory writes happen before
the Run row commits; on Lethe failure we still commit the Run with
`phase7_memory_item_ids = []` (graceful degradation).

## Error handling

| Failure | Behavior |
|---|---|
| Soteria raises (policy violation, runtime error) | Catch in handler; `phase7_retry_stop_reason = "error"`, `phase7_attempts = N`; persist Run anyway; log with `run_id`. |
| Lethe write fails (DB locked, disk full) | `phase7_memory_item_ids = []`; persist Run anyway; log with `run_id`. |
| Lethe per-project SQLite path unwritable | Same as Lethe write failure. |
| Soteria exceeds max_runtime_seconds | Soteria raises `RuntimeTimeoutError`; we catch and record `StopReason.MAX_RUNTIME_EXCEEDED`. |
| `phase7_enabled=True` but deps not installed | Lazy-import in `studio/integrations/__init__.py`; first attempt raises `Phase7DependencyError`; handler returns HTTP 503 with descriptive message; FastAPI app stays up. |

Phase 7 failures never break the user's check — they degrade gracefully
and surface state via the Run row + logs.

## Concurrency

- Single uvicorn worker for v1 (Phase 5 baseline).
- Lethe per-project DBs: open in WAL mode (Lethe's default).
- Phase 5 Studio DB: `check_same_thread=False` (existing); same setting
  applied to Phase 7 per-project DBs.

## Install

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
phase7 = [
    # Local editable installs during development
    "../Loopward",
    "../Lethe",
]
```

PyPI alternative (release path, documented but not the dev default):
```bash
pip install soteria-loop lethe-agent
```

## Testing strategy

### Unit tests

`studio/tests/test_phase7_soteria.py` and `studio/tests/test_phase7_lethe.py`:

- Pure integration boundary tests with Soteria's `FakeProvider` and
  Lethe's `InMemoryBackend` (no SQLite).
- Coverage:
  - `run_retry` exits with `REPEATED_ACTION` after `max_attempts` repeated verify calls.
  - `run_retry` returns the final verdicts from the last verify call.
  - `write_supported_claims` writes exactly one MemoryItem per `entailed` verdict.
  - Each MemoryItem has the expected `tags` and `metadata`.
  - `recall_run_claims(project_id, run_id)` round-trips.

### Integration tests

`studio/tests/test_phase7_api.py`:

- Real FastAPI TestClient + real SQLite + real Soteria runtime + real
  per-project Lethe SQLite.
- Cases:
  - `phase7_enabled=False` (default): no retry, no memory; Phase 5
    acceptance holds (regression).
  - `phase7_enabled=True` + blocked run: response carries
    `phase7_retry_stop_reason` and `phase7_attempts > 0`; Run row persists
    the same.
  - `phase7_enabled=True` + allowed run with two entailed verdicts: Lethe
    SQLite at `<db_dir>/phase7/{project_id}.sqlite` has exactly 2 memory
    items, both with the `run:{run_id}` tag.
  - `phase7_enabled=True` + flagged run: no retry, no memory.
  - Dependency missing: handler returns 503; FastAPI app still starts.

### Smoke / E2E

`studio/examples/studio_phase7_smoke_test.py`:

- Mirrors Phase 5 `studio_smoke_test.py` pattern: boots the real server,
  walks the Phase 7 acceptance end-to-end.
- Asserts:
  - Deliberately-blocked run triggers bounded Soteria retry (StopReason
    recorded, attempt count > 0).
  - Deliberately-allowed run writes supported claims to Lethe (memory
    count = entailed verdict count, each tagged with the run_id).

### Acceptance criteria checklist

- [x] "deliberately-blocked run triggers a bounded, observable Soteria retry
  (not an infinite loop, not a silent failure)" — `test_phase7_soteria.py`
  unit + `test_phase7_api.py` integration + smoke.
- [x] "deliberately-allowed run results in exactly the supported claims
  (and only those) appearing in Lethe's memory store, each traceable back
  to its verification run id" — `test_phase7_lethe.py` unit +
  `test_phase7_api.py` integration + smoke.
- [x] "Both integrations live in the Studio backend, not in the Elenchus
  library itself" — `grep -r "soteria_loop\|lethe\b" elenchus/` returns
  empty (verified in pre-implementation grep + post-implementation check).

## File structure

```
studio/
├── api/
│   └── app.py                                # MODIFIED (gate policy model, CheckResponse, /checks handler)
├── db/
│   └── store.py                              # MODIFIED (Phase 7 column migration, helper methods)
├── integrations/                             # NEW (was empty)
│   ├── __init__.py                           # NEW (public API + lazy imports)
│   ├── soteria.py                            # NEW
│   └── lethe.py                              # NEW
├── tests/
│   ├── test_phase7_soteria.py                # NEW
│   ├── test_phase7_lethe.py                  # NEW
│   ├── test_phase7_api.py                    # NEW
│   └── test_api.py                           # UNCHANGED (Phase 5 still passes)
├── examples/
│   └── studio_phase7_smoke_test.py           # NEW
└── README.md                                 # MODIFIED (Phase 7 section + endpoint table)
README.md                                     # MODIFIED (Phase 7 status: ✅)
pyproject.toml                                # MODIFIED ([phase7] extra: -e ../Loopward ../Lethe)
```

## Out-of-scope (deferred)

- Cross-project Lethe recall (v1.5).
- Real sentence-transformers embeddings in Lethe (v1.5).
- Multi-worker uvicorn for Phase 7 retries (v1.5).
- Side-by-side comparison UI for Phase 7 retries (v1.5; Phase 6 v1.5).
- FaithBench real run (already deferred in Phase 3).