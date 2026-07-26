# Elenchus — Rules

Non-negotiable invariants. These hold across every phase, regardless of what
else changes. If a change would violate one of these, stop and flag it
instead of proceeding.

## Configuration

1. **`VerificationConfig` is the single source of truth for user-facing
   production verification tunables.** Confidence-gap threshold, NLI
   decision threshold, NLI model name, max evidence passages, and max
   adjacent evidence-window chunks all live there. Deterministic algorithm
   coefficients remain named implementation constants, not hidden knobs.
   Benchmark-only baseline/judge settings stay outside production config but
   must be exposed as CLI arguments or named constants and serialized with
   every result.
2. Same principle for Studio: the Output Gate's policy is configuration, not
   hardcoded logic buried in the API layer.

## Verification behavior

3. **No silent guessing.** If a claim is ambiguous and no LLM judge is
   configured, the verdict is `unverifiable` — never a forced guess dressed
   up as a confident answer. Every phase that touches escalation logic needs
   a test proving this explicitly.
4. **Every check is logged.** No verdict is produced without a corresponding
   entry in the Verification Log — claim, evidence, verdict, confidence,
   tier, timestamp. Silent, unlogged verification defeats the point of the
   whole system.
5. **One verification code path.** `StreamingVerifier` and the batch
   `Verifier` must produce identical verdicts for identical input — proven
   by a test that feeds the same finished text through both and compares
   results, not asserted in prose. They also use the same sentence-boundary
   parser; token chunking must not change claim boundaries.

## Dependency boundaries

6. **The `elenchus/` library never imports Soteria or Lethe.** Those
   integrations live entirely under `studio/integrations/`. If implementing
   a feature seems to require importing one of them into the library, stop
   and flag it — that's a sign the feature belongs in Studio instead.
7. **Studio is a consumer of the library, not a special case of it.** Studio
   calls `elenchus.verifier` and `elenchus.streaming` the same way any
   external user of the library would — no reaching into private internals
   that aren't part of the public API.

## Dataset handling

8. **Benchmarks use the production verification path and keep datasets
   distinct.** Elenchus predictions call the public `Verifier`; benchmark code
   does not reimplement confidence routing or abstention. RAGTruth and
   FaithBench numbers are reported separately, never combined into one
   metric, because they answer different questions. A proxy dataset must be
   named as a proxy and must never be presented as a completed FaithBench run.

## Process

9. **Stop after each phase for review**, per Plan.md. Verified evidence
   (actual command output, actual rendered examples) accompanies every
   "phase complete" report — a claim of correctness without something to
   look at directly is not sufficient.
10. Unflattering results get reported plainly, not smoothed over — if the
    escalation tier doesn't help much, if a benchmark number is worse than
    expected, say so in RESULTS.md rather than reframing it.
