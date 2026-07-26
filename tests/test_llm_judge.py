"""Tests for the LLM judge interface. Rule 3 applies here directly:

no configured judge → ambiguous claim resolves to 'unverifiable', never a
silent guess. The test below proves this explicitly.
"""

from datetime import datetime, timezone

from elenchus.config import VerificationConfig
from elenchus.llm_judge import invoke_judge
from elenchus.types import Claim, Evidence


def _claim() -> Claim:
    return Claim(id="c1", text="A claim.", span=(0, 9))


def _evidence() -> list:
    return [
        Evidence(source_id="s1", text="supporting evidence.", span=(0, 20)),
    ]


def test_invoke_judge_calls_configured_judge() -> None:
    captured = {}

    def my_judge(claim: Claim, evidence: list) -> "Verdict":  # type: ignore[name-defined]  # noqa: F821
        captured["claim"] = claim
        captured["evidence"] = evidence
        return _verdict(label="supported", tier="llm_judge", confidence=0.9)

    cfg = VerificationConfig(llm_judge=my_judge)
    v = invoke_judge(cfg.llm_judge, _claim(), _evidence())
    assert v.label == "supported"
    assert v.tier == "llm_judge"
    assert captured["claim"].text == "A claim."


def test_no_judge_configured_returns_unverifiable_explicitly_rule_3() -> None:
    """Rule 3 — when the call would otherwise be a guess, say 'unverifiable'."""
    cfg = VerificationConfig()  # llm_judge=None
    assert cfg.llm_judge is None

    v = invoke_judge(cfg.llm_judge, _claim(), _evidence())

    # Honest verdict, no fake confidence, no forced label.
    assert v.label == "unverifiable"
    assert v.confidence == 0.0
    assert v.tier == "nli"
    assert v.evidence is None
    assert isinstance(v.checked_at, datetime)


def test_unverifiable_fallback_carries_claim_through() -> None:
    """Even when the judge isn't there, the returned verdict must point at
    the same claim — otherwise it's not a real fallback for the upstream
    pipeline."""
    cfg = VerificationConfig()
    c = _claim()
    v = invoke_judge(cfg.llm_judge, c, _evidence())
    assert v.claim is c


# ---- helpers ------------------------------------------------------------


def _verdict(label: str, tier: str, confidence: float) -> "Verdict":  # type: ignore[name-defined]  # noqa: F821
    from elenchus.types import Verdict

    return Verdict(
        claim=_claim(),
        label=label,  # type: ignore[arg-type]
        confidence=confidence,
        tier=tier,  # type: ignore[arg-type]
        evidence=_evidence()[0],
        checked_at=datetime.now(timezone.utc),
    )
