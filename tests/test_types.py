"""Structural tests for the data shapes defined in .context/Schema.md.

These shapes are used throughout the library — keeping their construction sane
in one place keeps the implementation files free of dataclass boilerplate.
"""

from datetime import datetime, timezone

from elenchus.types import Claim, Evidence, Verdict, LogEntry


def test_claim_carries_text_and_span() -> None:
    c = Claim(id="c1", text="Paris is the capital of France.", span=(0, 34))
    assert c.id == "c1"
    assert c.text == "Paris is the capital of France."
    assert c.span == (0, 34)
    assert c.text[c.span[0] : c.span[1]] == "Paris is the capital of France."


def test_evidence_carries_source_id_and_text_and_span() -> None:
    e = Evidence(
        source_id="kb-001",
        text="The capital of France is Paris.",
        span=(0, 34),
    )
    assert e.source_id == "kb-001"
    assert e.text == "The capital of France is Paris."
    assert e.span == (0, 34)
    assert e.text[e.span[0] : e.span[1]] == "The capital of France is Paris."


def test_verdict_label_is_one_of_allowed_values() -> None:
    # Schema.md labels: "supported" | "contradicted" | "unverifiable"
    # tier: "nli" | "llm_judge"
    for label in ("supported", "contradicted", "unverifiable"):
        for tier in ("nli", "llm_judge"):
            v = Verdict(
                claim=Claim(id="x", text="t", span=(0, 1)),
                label=label,  # type: ignore[arg-type]
                confidence=0.5,
                tier=tier,  # type: ignore[arg-type]
                evidence=None,
                checked_at=datetime.now(timezone.utc),
            )
            assert v.label == label
            assert v.tier == tier


def test_log_entry_wraps_verdict_with_timestamp() -> None:
    v = Verdict(
        claim=Claim(id="x", text="t", span=(0, 1)),
        label="supported",
        confidence=0.9,
        tier="nli",
        evidence=Evidence(source_id="s", text="t", span=(0, 1)),
        checked_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    e = LogEntry(verdict=v, logged_at=datetime(2025, 1, 2, tzinfo=timezone.utc))
    assert e.verdict is v
    assert e.logged_at == datetime(2025, 1, 2, tzinfo=timezone.utc)
