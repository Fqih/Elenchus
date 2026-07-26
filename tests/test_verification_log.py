"""Acceptance criterion #3 + Rule 4: every check is logged, never silently skipped."""

from datetime import datetime, timezone

from elenchus.types import Claim, Evidence, Verdict
from elenchus.verification_log import InMemoryVerificationLog


def _make_verdict(label: str, source_text: str = "supporting evidence.") -> Verdict:
    return Verdict(
        claim=Claim(id="c1", text="a claim", span=(0, 8)),
        label=label,  # type: ignore[arg-type]
        confidence=0.9,
        tier="nli",
        evidence=Evidence(
            source_id="src1", text=source_text, span=(0, len(source_text))
        ),
        checked_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def test_append_records_entry_with_evidence() -> None:
    log = InMemoryVerificationLog()
    v = _make_verdict("supported", "the capital of France is Paris.")
    log.append(v)

    entries = log.entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.verdict is v
    assert entry.verdict.evidence is not None
    assert entry.verdict.evidence.text == "the capital of France is Paris."
    assert entry.logged_at is not None


def test_entries_are_in_insertion_order() -> None:
    log = InMemoryVerificationLog()
    v1 = _make_verdict("supported")
    v2 = _make_verdict("contradicted")
    v3 = _make_verdict("unverifiable")
    log.append(v1)
    log.append(v2)
    log.append(v3)

    labels = [e.verdict.label for e in log.entries()]
    assert labels == ["supported", "contradicted", "unverifiable"]


def test_log_records_per_check_no_skips() -> None:
    """Rule 4 structurally: three distinct verifications → three entries, never two."""
    log = InMemoryVerificationLog()
    verdicts = [
        _make_verdict("supported"),
        _make_verdict("contradicted"),
        _make_verdict("unverifiable"),
    ]
    for v in verdicts:
        log.append(v)
    assert len(log.entries()) == 3
