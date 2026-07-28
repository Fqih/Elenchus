# Elenchus

Per-claim faithfulness checking for LLM/RAG output.

Elenchus splits an LLM's response into claims, checks each one against
the source material using a local NLI model by default, and escalates
ambiguous claims to an optional LLM judge. Every verdict is logged with
its evidence span.

The flagship use case is a customer-support RAG bot: Elenchus sits
between the bot's answer and the user, flags anything unsupported
before it ships, and writes the verdict trail to an append-only log.

## Why per-claim, not per-response?

A single "faithfulness: 0.82" score doesn't tell you which sentence
failed or why. Per-claim verdicts with span-level evidence do.

## Why a local NLI model by default?

Most faithfulness-checking tools rely on an LLM to judge another LLM,
which is expensive, slow, and structurally circular (the judge can
hallucinate too). Elenchus defaults to `cross-encoder/nli-deberta-v3-base`
— runs on a CPU, costs zero per claim, and gets called per claim so
the bottleneck scales with how much the model says, not how much the
source is.

## What's in here

```
elenchus/
├── types.py              Claim, Evidence, Verdict, LogEntry (Schema.md shapes)
├── config.py             VerificationConfig — single source of truth for tunables
├── claim_extractor.py    Sentence-level extraction with span round-trip
├── evidence_retriever.py Source chunking → candidate evidence per claim
├── nli_verifier.py       Tier 1: cross-encoder NLI
├── llm_judge.py          Tier 2 escalation helper (Rule 3 enforcement)
├── verifier.py           Batch orchestrator
├── streaming.py          StreamingVerifier — Rule 5, shared code path
├── verification_log.py   InMemory + SQLite backends
└── rendering.py          ANSI + HTML span rendering

benchmark/
├── prepare_dataset.py    RAGTruth → per-sentence gold labels
├── run_benchmark.py      Cosine / NLI-only / Tiered comparison
├── faithbench_stress.py  RAGTruth implicit-true escalation proxy
├── RESULTS.md            Numbers + honest caveats
└── data/                 Downloaded RAGTruth + prepared dataset + JSON results

examples/
├── phase1_demo.py
├── phase2_demo.py
├── customer_support_demo.py    Flagship demo (rendered output)
└── streaming_guardrail_demo.py Phase 4 streaming guardrail

studio/
├── api/                  FastAPI app + uvicorn entry point
├── db/                   StudioStore (Project, SourceDocument, Run, GatePolicy)
├── frontend/             Phase 6+: React + TypeScript + Vite
│   ├── src/components/   MemoryClaimsViewer (Phase 8), RunResult, etc.
│   └── tests/            vitest — 43 tests across Phase 8/16 components
├── gate.py               Output gate — pure function (Rule 2)
├── integrations/         Phase 7: Soteria adapter + Lethe adapter (lazy)
│   ├── __init__.py       Module-level lazy proxies + Phase7DependencyError
│   ├── soteria.py        run_retry(verifier, cfg, ...) → RetryResult
│   └── lethe.py          write_supported_claims / recall_run_claims
├── examples/             studio_smoke_test.py (Phase 5)
│                         studio_phase7_smoke_test.py (Phase 7 acceptance)
└── tests/                95 tests — gate(11) + store(20) + api(19)
                          + phase7-schema(5) + phase7-soteria(4)
                          + phase7-lethe(5) + phase7-api(4) + recall(6)
                          + auth(8) + metrics(5) + docker(8)

tests/                    Unit, integration, streaming, and benchmark tests

.github/
└── workflows/
    └── ci.yml            Phase 8: GitHub Actions — pytest + frontend
                          typecheck/vitest on push/PR to main
```

## Install

```bash
# Library + NLI model + benchmark tooling
pip install -e ".[dev]"

# The cross-encoder NLI model is downloaded on first use (~700MB).
# The sentence-transformers MiniLM model for the cosine baseline is
# downloaded on first benchmark run (~80MB).
```

## Quick commands (one Makefile at the repo root)

```bash
make help         # list every target with a one-liner
make install      # pip install backend (with Phase 7 if available)
make test         # pytest across tests/, benchmark/tests/, studio/tests/
make serve        # FastAPI server on :8765
make smoke        # Phase 5 E2E acceptance
make smoke7       # Phase 7 E2E acceptance (Soteria + Lethe)
make fe-install   # npm ci in studio/frontend
make fe-test      # vitest in studio/frontend
make fe-typecheck # tsc --noEmit in studio/frontend
make fe-dev       # vite dev server on :5173
make fe-build     # vite build to studio/frontend/dist
make dev          # run backend (:8765) AND frontend (:5173) together
make ci           # the full local CI gate (test + fe-test + fe-typecheck)
```

The `dev` target spawns both processes in one terminal with prefixed
output (`[api] …` / `[frontend] …`) and kills both on Ctrl-C — no more
two-tab dance.

### Docker (single-container)

```bash
make docker-build                  # builds the backend + frontend into one image
ELENCHUS_API_TOKEN=secret make docker-up     # bring it up on :8765
make docker-down                   # tear it down (keeps the SQLite volume)
```

The image bundles the React production build so the same FastAPI process
serves both `/api/*` and the SPA at the same origin. SQLite + per-project
Lethe files land in a named volume (`elenchus-data`) so state survives
container restarts.

Phase 7 (Soteria + Lethe) is **off by default**; build with
`INSTALL_PHASE7=1` after mounting the local Loopward/Lethe checkouts.
Without them the relevant `/checks` requests return 503 per the Phase 7
spec — the rest of the API still works.

## Quickstart

```python
from elenchus import (
    Verifier, VerificationConfig, InMemoryVerificationLog, render_ansi,
)
from elenchus.verification_log import SQLiteVerificationLog

cfg = VerificationConfig(confidence_gap_threshold=0.15)
log = SQLiteVerificationLog("verdicts.sqlite")
verifier = Verifier(config=cfg, log=log)

source = [("kb", "The Eiffel Tower in Paris attracts 7 million visitors a year.")]
output_text = "The Eiffel Tower is in Paris. Millions visit each year."
verdicts = verifier.verify(
    output_text=output_text,
    source_documents=source,
)

for v in verdicts:
    print(v.label, v.confidence, v.tier, v.claim.text)

print(render_ansi(output_text, verdicts))
```

For token-by-token verification (a guardrail that halts on
contradictions mid-stream):

```python
from elenchus import StreamingVerifier, Verifier

sv = StreamingVerifier(
    verifier=verifier,
    log=log,
    source_documents=source,
)

for token in bot_stream:
    sv.add_token(token)
    if sv.should_halt():
        break  # stop the response from going to the user
sv.finish()
```

## Streaming vs batch — they're the same (Rule 5)

`StreamingVerifier` and `Verifier` produce identical verdicts on the
same finished text. They share `Verifier.verify_claim` as the single
verification code path — proven by
`tests/test_streaming.py::test_streaming_and_batch_produce_identical_verdicts_*`,
not asserted in prose.

## Benchmark

RAGTruth results over the same 200-row sample for each of three seeds
(full precision/recall table and caveats in `benchmark/RESULTS.md`):

```
approach    detection F1    macro-F1        exact accuracy   escalation
cosine      0.103 ± 0.096   0.333 ± 0.017   0.878 ± 0.010    0%
nli_only    0.227 ± 0.034   0.366 ± 0.015   0.653 ± 0.029    0%
tiered      0.240 ± 0.027   0.372 ± 0.015   0.685 ± 0.029    31.2%
```

The tiered path improves detection F1, macro-F1, and exact label accuracy
over NLI-only while escalating 31.2% of claims. Its recall is slightly lower
(0.712 vs. 0.733), so this is a precision/accuracy improvement rather than a
win on every metric. Cosine's high exact accuracy is a majority-class effect:
it detects almost none of the hallucinations (recall 0.114).

The separate disputed-case stress run uses RAGTruth's explicit
`implicit_true=true` annotations as a development proxy. It is not presented
as a real FaithBench result. It escalates 77.3% of these hard cases; only
28.2% of escalated cases change label, so the routing remains intentionally
reported as an area for improvement.

### Reproducing the benchmark

```bash
python -m benchmark.prepare_dataset                       # downloads + preprocesses RAGTruth
python -m benchmark.run_benchmark --n 200 --seeds 1 2 3 --pool-size 5000
python -m benchmark.faithbench_stress --max-n 50 --seeds 1 2 3 --pool-size 30000
```

## Flagship demo

`examples/customer_support_demo.py` runs a synthetic customer-support
KB through Elenchus with a mix of clean and hallucinated bot answers.
Output:

```
========================================================================
Elenchus — flagship customer-support demo (Phase 3)
========================================================================

--- Case 2: 'How long does standard shipping take?' (hallucinated=True) ---
  [!!] contradicted  conf=1.00  tier=nli  claim='Standard shipping takes 1 to 2 business days within the continental United States.'
      evidence: 'Standard shipping takes 3 to 5 business days within the continental United St...'

Aggregate metrics (case-level: did we flag ANY claim?)
  detection rate : 100.0%
  false-positive : 0.0%
```

(See the demo script for the rendered ANSI + HTML output for one
clean and one hallucinated case.)

## Streaming guardrail demo

`examples/streaming_guardrail_demo.py` simulates a token-by-token bot
stream and halts on the first contradicted sentence:

```
Streaming bot output (live):
  Standard shipping takes 1 to 2 business days within the continental United States.

  >>> HALT: contradicted claim detected <<<

Verdicts produced during stream:
  [!!] #1  contradicted   conf=1.00  tier=nli  claim='Standard shipping takes 1 to 2 business days ...'
      evidence: 'Standard shipping takes 3 to 5 business days ...'
```

## Project status

Current implementation status:

- ✅ Phase 1: Core verification loop (Tier 1, in-memory log)
- ✅ Phase 2: Confidence-gap escalation, SQLite log, ANSI/HTML rendering
- 🟡 Phase 3: RAGTruth benchmark + flagship demo complete; the
  `implicit_true=true` stress proxy is complete, but a real FaithBench run is
  still pending
- ✅ Phase 4: StreamingVerifier + this README
- ✅ Phase 5: Studio FastAPI backend + SQLite store + output gate
- ✅ Phase 6: Studio frontend (React + TypeScript + Vite)
- ✅ Phase 7: Soteria retry + Lethe per-project memory (opt-in per project)
- ✅ Phase 8: Frontend + Ops polish — Phase 7 fields visible in the
  result panel, Lethe memory browser, recall endpoint, GitHub Actions CI,
  README updates
- ✅ Phase 9: Top-level Makefile — `make serve`, `make fe-dev`, `make dev`
  expose all backend + frontend operations from the repo root (no more
  `cd studio/frontend && …` to run the dev server)
- ✅ Phase 10: Production hardening — bearer-token auth, in-process rate
  limit, Prometheus `/metrics`, JSON-structured logs, `/health` endpoint
- ✅ Phase 11: HaluEval QA benchmark — `benchmark/halueval_runner.py`,
  test coverage for pair construction + metric math, `[eval]` optional-dep
- ✅ Phase 15: Docker packaging — `Dockerfile.backend` (multi-stage
  python+node build), `docker-compose.yml` with persistent volume and
  bearer-token env wiring, single-container deployment
- ✅ Phase 16: A/B model diff view — `RunCompareView` component in the
  project page (selectable left/right runs, per-claim DIFF badges for
  mismatched verdicts, same/differ row tinting). 5 new frontend tests.

## Studio (Phase 5)

`studio/` is a separate Python package that wraps the library in a
FastAPI service. It adds:

- Project lifecycle (create, list, get).
- Source-document CRUD with content-hash + version pinning.
- Verification-run submission wired to the library's public `Verifier`.
- An output gate (allowed/blocked/flagged) configurable per project.
- Run history with model/prompt labels for side-by-side comparison.

Run locally:

```bash
pip install -e ".[studio]"
python -m studio.api.server --db /tmp/studio.sqlite --port 8765
```

Walk the Phase 5 acceptance end-to-end:

```bash
LD_LIBRARY_PATH=$HOME/.local/lib python -m studio.examples.studio_smoke_test
```

The smoke test boots the real server, runs the full flow (project →
source → check → source edit → version-pin check → gate policy toggle →
run history), and prints every HTTP exchange. See `studio/README.md`
for the endpoint reference and Rule 6/7 walkthrough.

## Studio Phase 7 (Soteria + Lethe)

Phase 7 is an **opt-in**, per-project extension of the Studio backend:

- When a project's gate policy has `phase7_enabled=True`, a `blocked`
  run is handed to **Soteria** which retries the verification in an
  agent loop with bounds (`max_steps`, `max_runtime_seconds`,
  `repeated_action_limit`, `consecutive_error_limit`). The run row
  records `phase7_retry_attempts` and `phase7_retry_stop_reason`.
- When the same run is `allowed`, the **supported** claims are written
  to **Lethe** (one `MemoryItem` per claim) into a per-project SQLite
  at `<studio_db>/phase7/{project_id}.sqlite`. Each item is tagged with
  `run:{run_id}` so claims are traceable back to the verification run,
  and the row records `phase7_memory_item_ids`.
- When `phase7_enabled=False` (the default), nothing Phase 7 happens.

Install the optional deps:

```bash
pip install -e ".[phase7]"
```

Walk the Phase 7 acceptance end-to-end (boots the same real server as
the Phase 5 smoke test):

```bash
LD_LIBRARY_PATH=$HOME/.local/lib python -m studio.examples.studio_phase7_smoke_test
```

Missing-dep behavior: if `soteria-loop` or `lethe-agent` are not
installed, the relevant `/checks` request returns **HTTP 503** with a
message naming the missing package — the rest of the API still works.

Soft-fail: any other error inside a Phase 7 integration is swallowed
and the run is recorded with `phase7_retry_stop_reason="error"` (and no
memory ids), per Plan.md. Phase 7 is never load-bearing for the gate
decision.

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

## Studio Phase 8 (Frontend + Ops polish)

Phase 8 surfaces everything Phase 7 produced to the user, plus the
ops plumbing needed to ship it:

- **Phase 7 fields on every run row**: each `RunResult` now renders a
  compact "Phase 7" panel showing `Soteria retry` (attempts + stop
  reason) and `Lethe memory` (item count) when they are populated —
  off by default for projects that never enabled Phase 7.
- **Lethe memory browser**: a new `MemoryClaimsViewer` component lives
  under the Run history. When a run stored memory, the user can expand
  the claim list and read each stored `MemoryItem` (content, tags,
  importance score, access count).
- **Recall endpoint**: `GET /api/projects/{project_id}/runs/{run_id}/memory-claims`
  walks the per-project Lethe SQLite and returns the tagged items. It
  validates both the project and the run id (404 on miss) and never
  exposes Lethe embeddings in the wire format.
- **Cross-thread SQLite backend**: `studio/integrations/lethe.py` now
  uses a thread-safe subclass of Lethe's `SQLiteBackend`
  (`check_same_thread=False`) because FastAPI workers invoke from
  threads other than the one that created the connection.
- **GitHub Actions CI**: `.github/workflows/ci.yml` runs `pytest` (covers
  `tests/`, `benchmark/tests/`, `studio/tests/`) plus frontend
  `typecheck` and `vitest` on every push and PR to `main`. The Phase 7
  optional deps install gracefully falls back if the vendored
  Loopward/Lethe checkouts are absent.

Test counts after Phase 16: 95 studio tests (up from 68 after Phase 8,
Phases 10/15 added auth + metrics + docker packaging) + 43 frontend
tests (up from 29 after Phase 6, MemoryClaimsViewer +9, RunCompareView
+5). The full `pytest` run covers 204 tests across `tests/` (57),
`benchmark/tests/` (52), and `studio/tests/` (95).

## License

MIT (see `LICENSE`).
