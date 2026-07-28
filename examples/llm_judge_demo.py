"""Phase 12: worked example of a pluggable Tier 2 judge.

The `Verifier` only knows that a judge is "a callable taking a Claim and
a list of Evidence and returning a Verdict". You can plug in any function
or class with that shape via `VerificationConfig(llm_judge=...)`.

This example shows three ways to do it:

  1. A plain function (the most flexible — wrap any LLM call you like).
  2. `FunctionJudge` — same thing but with structured logging and a
     forced `tier="llm_judge"` field.
  3. `KeywordOverlapJudge` — the bundled deterministic judge (no LLM),
     useful as a baseline or as a unit-test stub.

The Verifier is intentionally invoked with a stub NLI that returns
ambiguous scores (gap < threshold) so the judge actually runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import List
from unittest.mock import MagicMock

import numpy as np

from elenchus import (
    Claim,
    EchoJudge,
    Evidence,
    FunctionJudge,
    KeywordOverlapJudge,
    VerificationConfig,
    Verifier,
    Verdict,
)
from elenchus.verification_log import InMemoryVerificationLog


def _stub_ambiguous_nli():
    """NLI that returns scores with a tiny gap → forces escalation to Tier 2."""
    nli = MagicMock(spec=["score", "verify", "verdict_from_scores"])
    nli.score.return_value = np.array([[0.45, 0.45, 0.10]])

    def from_scores(claim, evidence, scores, checked_at=None):
        return Verdict(
            claim=claim,
            label="supported",  # entail 0.45 > contradict 0.45 (tie, picked arbitrarily)
            confidence=0.45,
            tier="nli",
            evidence=evidence[0] if evidence else None,
            checked_at=checked_at or datetime.now().astimezone(),
        )

    nli.verdict_from_scores.side_effect = from_scores
    return nli


def example_1_plain_function() -> Verdict:
    """Wire any function as the judge — simplest possible contract."""

    def my_judge(claim: Claim, evidence: List[Evidence]) -> Verdict:
        # Imagine this calls OpenAI / Anthropic / local model.
        # The Verifier doesn't care, only the return type.
        return Verdict(
            claim=claim,
            label="supported",
            confidence=0.9,
            tier="llm_judge",
            evidence=evidence[0] if evidence else None,
            checked_at=datetime.now().astimezone(),
        )

    cfg = VerificationConfig(confidence_gap_threshold=0.15, llm_judge=my_judge)
    verifier = Verifier(config=cfg, log=InMemoryVerificationLog(), nli=_stub_ambiguous_nli())
    verdicts = verifier.verify(
        output_text="Standard shipping takes 3 to 5 days.",
        source_documents=[("kb", "Shipping policy: standard shipping 3-5 days.")],
    )
    return verdicts[0]


def example_2_function_judge() -> Verdict:
    """Wrap with FunctionJudge to get structured logs and tier enforcement."""

    def my_judge(claim: Claim, evidence: List[Evidence]) -> Verdict:
        return Verdict(
            claim=claim,
            label="supported",
            confidence=0.9,
            tier="nli",  # wrong tier — FunctionJudge fixes it
            evidence=evidence[0] if evidence else None,
            checked_at=datetime.now().astimezone(),
        )

    cfg = VerificationConfig(
        confidence_gap_threshold=0.15,
        llm_judge=FunctionJudge(my_judge, name="my_openai_wrapper"),
    )
    verifier = Verifier(config=cfg, log=InMemoryVerificationLog(), nli=_stub_ambiguous_nli())
    verdicts = verifier.verify(
        output_text="Standard shipping takes 3 to 5 days.",
        source_documents=[("kb", "Shipping policy: standard shipping 3-5 days.")],
    )
    return verdicts[0]


def example_3_keyword_overlap() -> Verdict:
    """Use the bundled deterministic judge — no LLM, fully reproducible."""
    cfg = VerificationConfig(
        confidence_gap_threshold=0.15,
        llm_judge=KeywordOverlapJudge(threshold=0.3),
    )
    verifier = Verifier(config=cfg, log=InMemoryVerificationLog(), nli=_stub_ambiguous_nli())
    verdicts = verifier.verify(
        output_text="Standard shipping takes 3 to 5 days.",
        source_documents=[("kb", "Shipping policy: standard shipping takes 3 to 5 days.")],
    )
    return verdicts[0]


def main() -> None:
    for label, fn in (
        ("plain function", example_1_plain_function),
        ("FunctionJudge wrapper", example_2_function_judge),
        ("KeywordOverlapJudge (bundled)", example_3_keyword_overlap),
    ):
        v = fn()
        print(f"[{label}] label={v.label} tier={v.tier} confidence={v.confidence:.2f}")


if __name__ == "__main__":
    main()
