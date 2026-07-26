"""Phase 1 acceptance criterion #2 (Tier 1, real model):

A known (claim, source) entailment pair labels 'supported' with high confidence.
A known contradiction pair labels 'contradicted' with high confidence.

The model is loaded once per session via a module-scoped pytest fixture so we
don't re-download weights per test.
"""

from datetime import datetime, timezone

import pytest

from elenchus.config import VerificationConfig
from elenchus.types import Claim, Evidence
from elenchus.nli_verifier import NliVerifier


@pytest.fixture(scope="module")
def verifier() -> NliVerifier:
    cfg = VerificationConfig()
    return NliVerifier(config=cfg)


def _claim(text: str) -> Claim:
    return Claim(id="c1", text=text, span=(0, len(text)))


def _evidence(text: str) -> Evidence:
    return Evidence(source_id="kb", text=text, span=(0, len(text)))


def test_obvious_entailment_returns_supported_with_high_confidence(
    verifier: NliVerifier,
) -> None:
    source = "The capital of France is Paris."
    claim_text = "Paris is the capital of France."
    v = verifier.verify(
        claim=_claim(claim_text),
        evidence=[_evidence(source)],
        checked_at=datetime.now(timezone.utc),
    )
    assert v.label == "supported", (
        f"expected supported, got {v.label} (conf {v.confidence})"
    )
    assert v.tier == "nli"
    assert v.confidence > 0.7, f"expected high confidence, got {v.confidence}"
    assert v.evidence is not None
    assert "Paris" in v.evidence.text
    assert isinstance(v.checked_at, datetime)


def test_directional_entailment_uses_evidence_as_premise(
    verifier: NliVerifier,
) -> None:
    """A specific source can entail a broader claim, but not vice versa.

    This regression test catches accidentally passing ``(claim, evidence)``
    to the directional premise/hypothesis NLI model.
    """
    source = "The Eiffel Tower in Paris attracts about 7 million visitors a year."
    claim_text = "Millions visit the Eiffel Tower each year."
    v = verifier.verify(
        claim=_claim(claim_text),
        evidence=[_evidence(source)],
        checked_at=datetime.now(timezone.utc),
    )
    assert v.label == "supported", (
        f"expected evidence to entail claim, got {v.label} (conf {v.confidence})"
    )
    assert v.confidence > 0.9
    assert v.evidence is not None


def test_obvious_contradiction_returns_contradicted_with_high_confidence(
    verifier: NliVerifier,
) -> None:
    source = "The capital of France is Paris."
    claim_text = "The capital of France is Berlin."
    v = verifier.verify(
        claim=_claim(claim_text),
        evidence=[_evidence(source)],
        checked_at=datetime.now(timezone.utc),
    )
    assert v.label == "contradicted", (
        f"expected contradicted, got {v.label} (conf {v.confidence})"
    )
    assert v.tier == "nli"
    assert v.confidence > 0.7, f"expected high confidence, got {v.confidence}"


def test_picks_strongest_signal_when_multiple_evidences(
    verifier: NliVerifier,
) -> None:
    """Relevant support wins over a strong signal from unrelated evidence."""
    good = "The capital of France is Paris."
    unrelated = "Bananas are a tropical fruit."
    claim_text = "Paris is the capital of France."
    v = verifier.verify(
        claim=_claim(claim_text),
        evidence=[_evidence(unrelated), _evidence(good)],
        checked_at=datetime.now(timezone.utc),
    )
    assert v.label == "supported"
    assert v.evidence is not None
    assert "Paris" in v.evidence.text
