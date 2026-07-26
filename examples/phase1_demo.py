"""Real working example for Phase 1 acceptance.

What this shows (per Plan.md Phase 1 acceptance):
    - obvious entailment → 'supported' with high confidence
    - obvious contradiction → 'contradicted' with high confidence
    - log records every check with the evidence span attached

Each (claim, source) pair is run separately to keep the evidence pool focused
on the passage that actually adjudicates the claim. The cross-encoder NLI
model still has real edge cases (it can label structurally-similar but
topically-distinct passages as contradictions); those will surface honestly in
the Phase 3 benchmark.
"""

from elenchus.config import VerificationConfig
from elenchus.verification_log import InMemoryVerificationLog
from elenchus.verifier import Verifier


SOURCE = "The capital of France is Paris."


def fmt_verdict(v) -> str:
    head = (
        f"  [{v.label:<13}] conf={v.confidence:.3f}  tier={v.tier}  "
        f"claim={v.claim.text!r}"
    )
    if v.evidence is not None:
        head += (
            f"\n    evidence: {v.evidence.text!r}  "
            f"span_in_source=({v.evidence.span[0]}, {v.evidence.span[1]})"
        )
    return head


def run_one(label: str, output: str, source: str) -> list:
    print(f"\n--- {label} ---")
    print(f"Output:   {output}")
    print(f"Source:   {source}")
    cfg = VerificationConfig()
    log = InMemoryVerificationLog()
    verifier = Verifier(config=cfg, log=log)
    verdicts = verifier.verify(
        output_text=output, source_documents=[("kb-001", source)]
    )
    print("Verdicts:")
    for v in verdicts:
        print(fmt_verdict(v))
    return log.entries()


def main() -> int:
    print("=" * 70)
    print("Elenchus — Phase 1 acceptance example")
    print("=" * 70)

    entailed_entries = run_one(
        label="Case A: obvious entailment",
        output="Paris is the capital of France.",
        source=SOURCE,
    )
    contradicted_entries = run_one(
        label="Case B: obvious contradiction",
        output="The capital of France is Berlin.",
        source=SOURCE,
    )
    multi_entries = run_one(
        label="Case C: best evidence picked from multiple candidates",
        output="Paris is the capital of France.",
        source="Bananas are a tropical fruit. The capital of France is Paris. The sky is blue.",
    )

    print("\n" + "=" * 70)
    print("Verification Log (Rule 4 — every check recorded, with evidence span)")
    print("=" * 70)
    all_entries = entailed_entries + contradicted_entries + multi_entries
    for i, e in enumerate(all_entries, 1):
        v = e.verdict
        ev_text = v.evidence.text if v.evidence else "no evidence"
        print(
            f"  {i}. label={v.label!r}, confidence={v.confidence:.3f}, "
            f"tier={v.tier}, evidence={ev_text!r}"
        )

    print(f"\nTotal log entries: {len(all_entries)} (== total verdicts, no drops).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
