# Elenchus — Plan

Seven phases, same discipline as Lethe: build, verify, stop for review, don't
move on until the acceptance criteria for the current phase are actually
checked, not just claimed.

## Phase 1 — Core verification loop (Tier 1 only)

Claim extraction (sentence-level), evidence retrieval that ranks all source
chunks before applying its configured top-k, directional local NLI
verification (`evidence` premise → `claim` hypothesis), `VerificationConfig`,
and an in-memory Verification Log. No LLM judge yet — prove the non-circular
default path works end to end first.

**Acceptance criteria**: given a known (claim, source) pair with an obvious
entailment and an obvious contradiction, the verifier returns the correct
label with high confidence for both, and the Verification Log records both
checks with the evidence span attached.

## Phase 2 — Escalation tier + span highlighting

Confidence-gap escalation logic, optional/injectable LLM judge, `Evidence`
spans wired through end to end, and a minimal rendering helper that produces
a side-by-side highlighted view (output claims color-coded, source evidence
excerpted). SQLite-backed Verification Log alongside the in-memory default.

**Acceptance criteria**: an ambiguous claim (deliberately constructed to sit
near the confidence-gap threshold) escalates to Tier 2 when a judge is
configured, and resolves to `unverifiable` — not a guess — when no judge is
configured. The rendering helper produces correct highlighted spans for a
multi-claim example.

## Phase 3 — Benchmark + flagship demo

Benchmark harness against **RAGTruth** (primary — precision/recall/F1 against
its span-level ground truth), with the cosine-similarity and
NLI-only-no-escalation baselines for comparison. Separately, a stress-test
against **FaithBench** to check whether the confidence-gap threshold
correctly routes known-hard/disputed cases to Tier 2. When FaithBench is not
available locally, an explicitly named RAGTruth `implicit_true=true` proxy
may be reported for development feedback, but does not satisfy the real
FaithBench acceptance item. Synthetic customer-support demo: a small
knowledge base, a mix of clean and
deliberately-hallucinated bot answers, run through Elenchus, reported
detection/false-positive rates. All Elenchus benchmark predictions must call
the public `Verifier`; the benchmark must not copy its routing logic.

**Acceptance criteria**: hallucination-detection precision/recall/F1 and
exact three-way accuracy/macro-F1 exist and are stable across at least 3
dataset shuffles/seeds where applicable; real FaithBench results are clearly
distinguished from any proxy; the flagship demo produces a rendered
side-by-side view for at least one hallucinated and one clean example,
checked by eye, not just asserted by a test.

## Phase 4 — Streaming verifier + polish

`StreamingVerifier`, a single sentence-boundary parser shared with batch mode
and benchmark preprocessing, a runnable example simulating a token stream
with a guardrail that halts on a contradicted claim, and a final README with
the benchmark numbers and the flagship demo screenshot/output embedded.

**Acceptance criteria**: the streaming example detects and halts on an
injected contradiction mid-stream, and produces the same verdict a
batch-mode call on the same finished text would have produced — streaming
and batch must agree, since they share one verification code path by design.

## Phase 5 — Studio backend API

FastAPI service wrapping the library: project creation, adding/updating
source documents (with content-hash and version tracking per Schema.md),
submitting a check (paste-and-verify only — no generation endpoint, see
Rules.md), retrieving verdicts with spans, run history, output gate
configuration and evaluation using the explicit precedence algorithm in
Schema.md. No frontend yet — this phase is verified via API calls
(curl/httpie/tests), not a UI.

**Acceptance criteria**: creating a project, adding a source document,
submitting a check, and retrieving its verdicts round-trips correctly
through the API; editing a source document bumps its version and a
previously-recorded run still points at the version it was actually checked
against; a configured output gate correctly labels a run as
allowed/blocked/flagged using the blocked > flagged > allowed precedence;
run history for a project lists all past runs in order with their recorded
model/prompt labels and latency.

## Phase 6 — Studio frontend

A minimal web UI: upload/paste source documents, paste an existing candidate
answer, view claims color-coded by verdict with evidence spans on click,
side-by-side comparison view for multiple model/prompt runs, and a history
view per project. Candidate generation remains out of scope for v1.

**Acceptance criteria**: a person with no prior context can upload a source
document, paste an answer with one deliberately false claim, and correctly
identify which claim was flagged and why, using only the UI — no reading
API responses directly.

## Phase 7 — Soteria + Lethe integration

Wire the output gate's "blocked" path to a Soteria-managed retry loop, and
the "allowed" path to writing verified claims into a Lethe `MemoryStore`.
Both integrations live in the Studio backend, not in the Elenchus library
itself — Elenchus stays framework/tool-agnostic.

**Acceptance criteria**: a deliberately-blocked run triggers a bounded,
observable Soteria retry (not an infinite loop, not a silent failure); a
deliberately-allowed run results in exactly the supported claims (and only
those) appearing in Lethe's memory store, each traceable back to its
verification run id.

## Deferred (not v1)

- Multi-language NLI models.
- Sub-sentence claim decomposition (splitting compound sentences into
  finer-grained atomic claims).
- Automatic correction/rewriting of ungrounded claims.
