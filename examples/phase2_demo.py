"""Phase 2 acceptance demo.

Shows three things, per Plan.md Phase 2 + Rule 3:

    1. An ambiguous claim, run against the live NLI model, sits near the
       confidence-gap threshold and escalates to Tier 2 when a judge is
       configured.
    2. The same ambiguous claim, with no judge, resolves to 'unverifiable'.
    3. The rendering helper produces a colored span view of the output
       text plus evidence excerpts.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from elenchus.config import VerificationConfig
from elenchus.rendering import render_ansi, render_html
from elenchus.types import Claim, Evidence, Verdict
from elenchus.verification_log import InMemoryVerificationLog, SQLiteVerificationLog
from elenchus.verifier import Verifier


# A claim that's borderline to a typical NLI model — paraphrased enough that
# the cross-encoder produces similar probabilities for entail vs contradict.
SOURCE = "The Eiffel Tower in Paris attracts about 7 million visitors a year."


def _stub_judge(label: str = "supported", confidence: float = 0.8):
    judge = MagicMock()
    judge.side_effect = lambda claim, evidence: Verdict(
        claim=claim,
        label=label,  # type: ignore[arg-type]
        confidence=confidence,
        tier="llm_judge",
        evidence=(evidence[0] if evidence else None),
        checked_at=datetime.now(timezone.utc),
    )
    return judge


def case_with_judge() -> list:
    """Ambiguous claim → escalates to Tier 2."""
    output = "Millions visit the Eiffel Tower each year."
    log = InMemoryVerificationLog()
    cfg = VerificationConfig(
        confidence_gap_threshold=0.15,
        llm_judge=_stub_judge(label="supported", confidence=0.78),
    )
    verifier = Verifier(config=cfg, log=log)
    return verifier.verify(output_text=output, source_documents=[("kb", SOURCE)])


def case_without_judge() -> list:
    """Same ambiguous claim → 'unverifiable' because no judge is configured."""
    output = "Millions visit the Eiffel Tower each year."
    log = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)  # no judge
    verifier = Verifier(config=cfg, log=log)
    return verifier.verify(output_text=output, source_documents=[("kb", SOURCE)])


def main() -> int:
    print("=" * 70)
    print("Elenchus — Phase 2 acceptance")
    print("=" * 70)

    print("\n--- Case 1: judge configured, ambiguous claim escalates ---\n")
    verdicts_with = case_with_judge()
    v = verdicts_with[0]
    print(f"  label       = {v.label!r}")
    print(f"  confidence  = {v.confidence:.3f}")
    print(f"  tier        = {v.tier!r}")
    print(f"  evidence    = {v.evidence.text if v.evidence else None!r}")

    print("\n--- Case 2: no judge configured, same claim → unverifiable ---\n")
    verdicts_no = case_without_judge()
    v2 = verdicts_no[0]
    print(f"  label       = {v2.label!r}")
    print(f"  confidence  = {v2.confidence:.3f}")
    print(f"  tier        = {v2.tier!r}")
    print(f"  evidence    = {v2.evidence}")

    print("\n--- Case 3: SQLite-backed log durability ---\n")
    db_path = Path("/tmp/elenchus_phase2_demo.sqlite")
    if db_path.exists():
        db_path.unlink()
    sqlite_log = SQLiteVerificationLog(str(db_path))
    sqlite_log.append(verdicts_with[0])
    sqlite_log.append(verdicts_no[0])
    print(f"  wrote 2 entries to {db_path}")
    print(f"  in-process entries: {len(sqlite_log.entries())}")
    sqlite_log.close()

    reloaded = SQLiteVerificationLog(str(db_path))
    reloaded_entries = reloaded.entries()
    print(f"  reloaded entries : {len(reloaded_entries)}")
    print(f"  labels           : {[e.verdict.label for e in reloaded_entries]}")
    print(f"  tiers            : {[e.verdict.tier for e in reloaded_entries]}")
    reloaded.close()
    if db_path.exists():
        db_path.unlink()

    print("\n--- Case 4: rendering helper, ANSI view ---\n")
    output = (
        "The Eiffel Tower is in Paris. "
        "Millions visit the Eiffel Tower each year. "
        "The Eiffel Tower is located on the Champs-Élysées."
    )
    c1_text = "The Eiffel Tower is in Paris."
    c2_text = "Millions visit the Eiffel Tower each year."
    c3_text = "The Eiffel Tower is located on the Champs-Élysées."
    c1_start = output.index(c1_text)
    c2_start = output.index(c2_text)
    c3_start = output.index(c3_text)
    verdicts_for_render = [
        Verdict(
            claim=Claim(
                id="c1", text=c1_text, span=(c1_start, c1_start + len(c1_text))
            ),
            label="supported",
            confidence=0.99,
            tier="nli",
            evidence=Evidence(source_id="kb", text=SOURCE, span=(0, len(SOURCE))),
            checked_at=datetime.now(timezone.utc),
        ),
        Verdict(
            claim=Claim(
                id="c2", text=c2_text, span=(c2_start, c2_start + len(c2_text))
            ),
            label="supported",
            confidence=0.85,
            tier="nli",
            evidence=Evidence(source_id="kb", text=SOURCE, span=(0, len(SOURCE))),
            checked_at=datetime.now(timezone.utc),
        ),
        Verdict(
            claim=Claim(
                id="c3", text=c3_text, span=(c3_start, c3_start + len(c3_text))
            ),
            label="contradicted",
            confidence=0.95,
            tier="nli",
            evidence=Evidence(source_id="kb", text=SOURCE, span=(0, len(SOURCE))),
            checked_at=datetime.now(timezone.utc),
        ),
    ]
    print(render_ansi(output, verdicts_for_render))

    print("\n--- Case 4 (alt): same input, HTML rendering ---\n")
    print(render_html(output, verdicts_for_render))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
