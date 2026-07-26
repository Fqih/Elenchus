"""SQLite-backed Verification Log — Phase 2.

Same interface as the in-memory log (`append`, `entries`), but durable across
process restarts. Tests use a per-test temp file so they don't trample each
other or leave debris.
"""

from datetime import datetime, timezone
from pathlib import Path

from elenchus.types import Claim, Evidence, Verdict
from elenchus.verification_log import SQLiteVerificationLog


def _make_verdict(
    label: str,
    source_text: str = "supporting evidence.",
) -> Verdict:
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


def test_append_persists_and_reloads(tmp_path: Path) -> None:
    db = tmp_path / "phase2_log.sqlite"
    log = SQLiteVerificationLog(str(db))
    log.append(_make_verdict("supported"))
    log.append(_make_verdict("contradicted"))
    assert len(log.entries()) == 2

    # A new instance pointed at the same file sees both entries.
    reloaded = SQLiteVerificationLog(str(db))
    entries = reloaded.entries()
    assert len(entries) == 2
    assert [e.verdict.label for e in entries] == ["supported", "contradicted"]
    assert entries[0].verdict.evidence is not None
    assert entries[0].verdict.evidence.text == "supporting evidence."


def test_entries_carry_logged_at_timestamp(tmp_path: Path) -> None:
    db = tmp_path / "phase2_log.sqlite"
    log = SQLiteVerificationLog(str(db))
    before = datetime.now(timezone.utc).timestamp()
    log.append(_make_verdict("unverifiable"))
    after = datetime.now(timezone.utc).timestamp()

    entries = log.entries()
    assert len(entries) == 1
    ts = entries[0].logged_at.timestamp()
    assert before <= ts <= after


def test_unverifiable_with_no_evidence_is_stored_intact(tmp_path: Path) -> None:
    db = tmp_path / "phase2_log.sqlite"
    log = SQLiteVerificationLog(str(db))
    v = Verdict(
        claim=Claim(id="c", text="x", span=(0, 1)),
        label="unverifiable",
        confidence=0.0,
        tier="nli",
        evidence=None,
        checked_at=datetime.now(timezone.utc),
    )
    log.append(v)

    [entry] = SQLiteVerificationLog(str(db)).entries()
    assert entry.verdict.label == "unverifiable"
    assert entry.verdict.evidence is None
    assert entry.verdict.confidence == 0.0


def test_empty_db_returns_empty_entries(tmp_path: Path) -> None:
    db = tmp_path / "phase2_log.sqlite"
    log = SQLiteVerificationLog(str(db))
    assert log.entries() == []
