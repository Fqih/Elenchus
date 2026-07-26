"""End-to-end batch verifier — Phase 1 acceptance:

Given known (claim, source) pairs with entailment and contradiction, the
verifier returns correct labels and the verification log records every check
with its evidence span attached.
"""

from elenchus.config import VerificationConfig
from elenchus.verification_log import InMemoryVerificationLog
from elenchus.verifier import Verifier


SOURCE_PARIS = "The capital of France is Paris."
SOURCE_BERLIN = "The capital of France is Berlin."


def test_end_to_end_entailed_and_contradicted_claims_both_logged() -> None:
    output = "Paris is the capital of France. The capital of France is Berlin."
    log = InMemoryVerificationLog()
    cfg = VerificationConfig()
    v = Verifier(config=cfg, log=log)

    verdicts = v.verify(output_text=output, source_documents=[("kb-001", SOURCE_PARIS)])

    assert len(verdicts) == 2
    labels = [verdict.label for verdict in verdicts]
    assert "supported" in labels, labels
    assert "contradicted" in labels, labels

    # Acceptance: every check is logged (Rule 4 — no silent drops).
    entries = log.entries()
    assert len(entries) == 2
    for entry in entries:
        assert entry.verdict.evidence is not None, (
            "every logged verdict must carry an evidence span — "
            "otherwise the log isn't actually useful"
        )


def test_returns_empty_verdict_list_for_empty_output() -> None:
    log = InMemoryVerificationLog()
    cfg = VerificationConfig()
    v = Verifier(config=cfg, log=log)
    assert (
        v.verify(output_text="   ", source_documents=[("kb-001", "irrelevant text.")])
        == []
    )
    assert len(log.entries()) == 0, "no claim → no log entry is correct here"


def test_claim_text_round_trip_against_output() -> None:
    """The claim text must slice cleanly back out of the original output text
    so the Phase 2 highlighter can paint the right pixels."""
    output = "Berlin is the capital of Germany."
    log = InMemoryVerificationLog()
    cfg = VerificationConfig()
    v = Verifier(config=cfg, log=log)
    verdicts = v.verify(
        output_text=output,
        source_documents=[("kb", "Berlin is the capital of Germany.")],
    )
    assert len(verdicts) == 1
    c = verdicts[0].claim
    assert output[c.span[0] : c.span[1]] == c.text
