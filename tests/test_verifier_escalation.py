"""Confidence-gap escalation — Phase 2.

The verifier must compute the gap between the top and second class from
NLI scores and use that to decide whether to escalate to Tier 2. When the
judge isn't configured, an ambiguous claim must resolve to 'unverifiable'
(Rule 3).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from elenchus.config import VerificationConfig
from elenchus.types import Claim, Evidence, Verdict
from elenchus.verification_log import InMemoryVerificationLog
from elenchus.verifier import Verifier


def _stub_nli_with_probs(contradict: float, entail: float, neutral: float) -> MagicMock:
    """Build a stub NliVerifier that returns a single (n=1) probability
    matrix `[contradict, entail, neutral]` from `score()`. Also supports
    `verify()` for the confident path.
    """
    import numpy as np

    stub = MagicMock(spec=["score", "verify", "verdict_from_scores"])
    stub.score.return_value = np.array([[contradict, entail, neutral]])

    # When the verdict path is taken in tests, build a Verdict manually.
    def fake_verify(claim, evidence, checked_at=None):
        return Verdict(
            claim=claim,
            label="supported" if entail > contradict else "contradicted",
            confidence=max(entail, contradict),
            tier="nli",
            evidence=evidence[0] if evidence else None,
            checked_at=checked_at or datetime.now(timezone.utc),
        )

    stub.verify.side_effect = fake_verify
    stub.verdict_from_scores.side_effect = (
        lambda claim, evidence, scores, checked_at=None: fake_verify(
            claim=claim,
            evidence=evidence,
            checked_at=checked_at,
        )
    )
    return stub


def test_high_gap_does_not_escalate_even_with_judge() -> None:
    """Tier 1 with a wide top-vs-second gap is confident — no escalation."""
    # gap = |0.95 - 0.04| = 0.91, way above default 0.15
    nli = _stub_nli_with_probs(contradict=0.04, entail=0.95, neutral=0.01)
    judge = MagicMock()
    cfg = VerificationConfig(
        confidence_gap_threshold=0.15,
        llm_judge=judge,
    )
    log = InMemoryVerificationLog()
    v = Verifier(config=cfg, log=log, nli=nli)

    result = v.verify(
        output_text="A claim.",
        source_documents=[("kb", "evidence text.")],
    )

    assert len(result) == 1
    assert result[0].label == "supported"
    assert result[0].tier == "nli"
    judge.assert_not_called()
    nli.verdict_from_scores.assert_called_once()
    nli.verify.assert_not_called()


def test_low_gap_with_judge_escalates_to_tier_2() -> None:
    """Tier 1 ambiguous → judge is invoked → verdict carries tier='llm_judge'."""
    # gap = |0.45 - 0.40| = 0.05, below default 0.15
    nli = _stub_nli_with_probs(contradict=0.40, entail=0.45, neutral=0.15)
    judge = MagicMock(
        return_value=Verdict(
            claim=Claim(id="c", text="A claim.", span=(0, 9)),
            label="contradicted",
            confidence=0.6,
            tier="llm_judge",
            evidence=Evidence(source_id="kb", text="supporting text", span=(0, 15)),
            checked_at=datetime.now(timezone.utc),
        )
    )
    cfg = VerificationConfig(
        confidence_gap_threshold=0.15,
        llm_judge=judge,
    )
    log = InMemoryVerificationLog()
    v = Verifier(config=cfg, log=log, nli=nli)

    result = v.verify(
        output_text="A claim.",
        source_documents=[("kb", "evidence text.")],
    )

    assert len(result) == 1
    assert result[0].label == "contradicted"
    assert result[0].tier == "llm_judge"
    judge.assert_called_once()
    # judge never called the second method since the gap closed it
    nli.verify.assert_not_called()


def test_low_gap_without_judge_returns_unverifiable_rule_3() -> None:
    """Rule 3: ambiguous + no judge = unverifiable, never a forced label."""
    nli = _stub_nli_with_probs(contradict=0.40, entail=0.45, neutral=0.15)
    cfg = VerificationConfig(confidence_gap_threshold=0.15)  # llm_judge=None
    log = InMemoryVerificationLog()
    v = Verifier(config=cfg, log=log, nli=nli)

    result = v.verify(
        output_text="A claim.",
        source_documents=[("kb", "evidence text.")],
    )

    assert len(result) == 1
    assert result[0].label == "unverifiable"
    assert result[0].evidence is None
    assert result[0].confidence == 0.0


def test_neutral_dominant_scores_escalate_even_when_decision_gap_is_wide() -> None:
    """A large entail-vs-contradict gap is not confidence when neutral wins."""
    nli = _stub_nli_with_probs(contradict=0.05, entail=0.35, neutral=0.60)
    judge = MagicMock(
        return_value=Verdict(
            claim=Claim(id="c", text="A claim.", span=(0, 8)),
            label="unverifiable",
            confidence=0.8,
            tier="llm_judge",
            evidence=None,
            checked_at=datetime.now(timezone.utc),
        )
    )
    cfg = VerificationConfig(
        confidence_gap_threshold=0.15,
        nli_decision_threshold=0.50,
        llm_judge=judge,
    )
    result = Verifier(
        config=cfg,
        log=InMemoryVerificationLog(),
        nli=nli,
    ).verify(
        output_text="A claim.",
        source_documents=[("kb", "evidence text.")],
    )

    assert result[0].tier == "llm_judge"
    assert result[0].label == "unverifiable"
    judge.assert_called_once()
    nli.verify.assert_not_called()


def test_escalation_threshold_is_configurable() -> None:
    """Rule 1: confidence_gap_threshold lives in VerificationConfig.
    Setting it to 0.0 forces every verdict through the gap path; setting it
    to 1.0 forces every verdict to be trusted from Tier 1 directly."""
    nli = _stub_nli_with_probs(contradict=0.10, entail=0.10, neutral=0.80)
    judge = MagicMock(
        return_value=Verdict(
            claim=Claim(id="c", text="x", span=(0, 1)),
            label="supported",
            confidence=0.9,
            tier="llm_judge",
            evidence=None,
            checked_at=datetime.now(timezone.utc),
        )
    )
    log = InMemoryVerificationLog()

    # threshold = 1.0 → all gaps < threshold → always escalate
    cfg_thr1 = VerificationConfig(confidence_gap_threshold=1.0, llm_judge=judge)
    Verifier(config=cfg_thr1, log=log, nli=nli).verify(
        output_text="x.", source_documents=[("kb", "evidence")]
    )
    assert judge.call_count == 1

    # threshold = 0.0 → no gap < 0.0 → never escalate
    judge.reset_mock()
    cfg_thr0 = VerificationConfig(
        confidence_gap_threshold=0.0,
        nli_decision_threshold=0.0,
        llm_judge=judge,
    )
    Verifier(config=cfg_thr0, log=log, nli=nli).verify(
        output_text="x.", source_documents=[("kb", "evidence")]
    )
    judge.assert_not_called()


def test_threshold_default_matches_schema() -> None:
    """Schema.md: confidence_gap_threshold default is 0.15."""
    assert VerificationConfig().confidence_gap_threshold == 0.15
