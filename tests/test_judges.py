"""Phase 12: pluggable Tier 2 judges.

The judge is whatever the user wires in via `VerificationConfig.llm_judge`.
These tests pin down the contract for the bundled judge helpers and prove
that a custom judge plugged in via `VerificationConfig` actually runs on
the Tier 2 escalation path.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

import pytest

from elenchus.config import VerificationConfig
from elenchus.judges import (
    EchoJudge,
    FunctionJudge,
    Judge,
    KeywordOverlapJudge,
)
from elenchus.types import Claim, Evidence, Verdict
from elenchus.verification_log import InMemoryVerificationLog
from elenchus.verifier import Verifier


def _claim(text: str = "the cat sat on the mat") -> Claim:
    return Claim(id="c1", text=text, span=(0, len(text)))


def _evidence(text: str = "the cat sat on the mat") -> Evidence:
    return Evidence(source_id="kb", text=text, span=(0, len(text)))


def test_judge_protocol_accepts_classes_and_callables() -> None:
    """Anything with `__call__(Claim, list[Evidence]) -> Verdict` is a Judge."""
    assert isinstance(EchoJudge(), Judge)
    assert isinstance(KeywordOverlapJudge(), Judge)
    assert isinstance(FunctionJudge(lambda c, e: None), Judge)  # type: ignore[arg-type]


def test_echo_judge_is_deterministic_and_ignores_evidence() -> None:
    """EchoJudge always returns supported with the highest confidence."""
    judge = EchoJudge()
    v1 = judge(_claim(), [_evidence("totally unrelated text")])
    v2 = judge(_claim(), [])
    assert v1.label == "supported"
    assert v1.tier == "llm_judge"
    assert v1.confidence == 0.99
    assert v2.label == "supported"
    assert v2.evidence is None  # empty list → no evidence carried


def test_keyword_overlap_judge_supports_when_overlap_high() -> None:
    """High Jaccard overlap → supported."""
    judge = KeywordOverlapJudge(threshold=0.3)
    v = judge(
        _claim("shipping takes 3 to 5 business days"),
        [_evidence("standard shipping takes 3 to 5 business days")],
    )
    assert v.label == "supported"
    assert v.tier == "llm_judge"
    assert v.confidence > 0.0
    assert v.evidence is not None


def test_keyword_overlap_judge_contradicts_when_overlap_low() -> None:
    """No token overlap → contradicted."""
    judge = KeywordOverlapJudge(threshold=0.5)
    v = judge(
        _claim("shipping takes 1 to 2 days"),
        [_evidence("returns within 60 days")],
    )
    assert v.label == "contradicted"
    assert v.tier == "llm_judge"
    assert v.evidence is not None


def test_keyword_overlap_judge_unverifiable_with_no_evidence() -> None:
    """No evidence → unverifiable, not contradicted."""
    judge = KeywordOverlapJudge()
    v = judge(_claim("anything"), [])
    assert v.label == "unverifiable"
    assert v.confidence == 0.0
    assert v.evidence is None


def test_function_judge_wraps_and_forces_tier() -> None:
    """FunctionJudge fixes `tier` to llm_judge if the wrapped fn forgot."""

    def raw(claim: Claim, evidence: List[Evidence]) -> Verdict:
        return Verdict(
            claim=claim,
            label="supported",
            confidence=0.7,
            tier="nli",  # wrong tier — FunctionJudge should fix it
            evidence=evidence[0] if evidence else None,
            checked_at=datetime.now().astimezone(),
        )

    judge = FunctionJudge(raw, name="raw_wrapper")
    v = judge(_claim(), [_evidence()])
    assert v.tier == "llm_judge"
    assert v.label == "supported"


def test_function_judge_delegates_to_inner_fn() -> None:
    """The wrapped function actually receives the inputs."""
    seen: list[tuple[Claim, List[Evidence]]] = []

    def spy(claim: Claim, evidence: List[Evidence]) -> Verdict:
        seen.append((claim, evidence))
        return Verdict(
            claim=claim,
            label="contradicted",
            confidence=0.5,
            tier="llm_judge",
            evidence=evidence[0] if evidence else None,
            checked_at=datetime.now().astimezone(),
        )

    judge = FunctionJudge(spy)
    claim = _claim()
    ev = _evidence()
    judge(claim, [ev])
    assert len(seen) == 1
    assert seen[0][0] is claim
    assert seen[0][1] == [ev]


def _stub_nli(contradict: float, entail: float, neutral: float):
    """Build a MagicMock NLI that returns scores and a verdict_from_scores that
    selects evidence[0] when entail > contradict."""
    from unittest.mock import MagicMock
    from datetime import datetime
    from elenchus.types import Verdict
    import numpy as np

    nli = MagicMock(spec=["score", "verify", "verdict_from_scores"])
    nli.score.return_value = np.array([[contradict, entail, neutral]])

    def from_scores(claim, evidence, scores, checked_at=None):
        return Verdict(
            claim=claim,
            label="supported" if entail > contradict else "contradicted",
            confidence=max(entail, contradict),
            tier="nli",
            evidence=evidence[0] if evidence else None,
            checked_at=checked_at or datetime.now().astimezone(),
        )

    nli.verdict_from_scores.side_effect = from_scores
    return nli


def test_custom_judge_runs_via_verification_config() -> None:
    """A judge plugged into VerificationConfig.llm_judge actually fires."""
    # NLI stub: gap = |0.45 - 0.40| = 0.05 → below threshold → escalate.
    nli = _stub_nli(contradict=0.40, entail=0.45, neutral=0.15)

    judge = EchoJudge()
    cfg = VerificationConfig(confidence_gap_threshold=0.15, llm_judge=judge)
    log = InMemoryVerificationLog()
    result = Verifier(config=cfg, log=log, nli=nli).verify(
        output_text="the cat sat.",
        source_documents=[("kb", "the cat sat on the mat.")],
    )

    assert len(result) == 1
    assert result[0].label == "supported"
    assert result[0].tier == "llm_judge"


def test_keyword_overlap_judge_via_verification_config_end_to_end() -> None:
    """A real (non-mock) judge wired through VerificationConfig drives the verdict."""
    nli = _stub_nli(contradict=0.45, entail=0.45, neutral=0.10)

    judge = KeywordOverlapJudge(threshold=0.3)
    cfg = VerificationConfig(confidence_gap_threshold=0.15, llm_judge=judge)
    log = InMemoryVerificationLog()
    result = Verifier(config=cfg, log=log, nli=nli).verify(
        output_text="standard shipping takes 3 to 5 days",
        source_documents=[
            ("kb", "shipping policy: standard shipping takes 3 to 5 business days")
        ],
    )
    assert result[0].tier == "llm_judge"
    assert result[0].label == "supported"


def test_keyword_overlap_threshold_boundary() -> None:
    """threshold=0.0 means any nonzero overlap counts as supported."""
    judge_zero = KeywordOverlapJudge(threshold=0.0)
    v = judge_zero(
        _claim("a b"),
        [_evidence("c d e f")],  # overlap = 0/6 = 0 — still below 0.0 is impossible
    )
    # With threshold=0.0 the only way to be contradicted is exactly 0 overlap,
    # which is the case here. So contradicted is the right answer.
    assert v.label == "contradicted"

    judge_any = KeywordOverlapJudge(threshold=0.0)
    v2 = judge_any(
        _claim("a"),
        [_evidence("a b c")],  # overlap > 0
    )
    assert v2.label == "supported"
