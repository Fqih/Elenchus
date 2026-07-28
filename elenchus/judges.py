"""Pluggable Tier 2 judges (Phase 12).

The Tier 2 judge in Elenchus is just a callable that takes a `Claim` plus the
candidate `Evidence` passages and returns a `Verdict`. This module gives
that callable a name, a protocol, and a few ready-made implementations so
users can swap judges without re-implementing the verifier integration.

The contract is intentionally narrow:

    judge(claim: Claim, evidence: list[Evidence]) -> Verdict

Any callable with that shape is accepted by `VerificationConfig.llm_judge`.
The helpers below wrap that contract in three forms:

- `Judge` — a `Protocol` describing the contract for type checkers.
- `FunctionJudge` — wraps a plain function with structured logging so users
  can see what was asked of the judge in production logs.
- `EchoJudge` / `KeywordOverlapJudge` — deterministic, no-LLM implementations
  that are useful as tests, smoke tests, and worked examples in docs.

If you want to plug in a real LLM (OpenAI / Anthropic / local), write a
function with the contract and pass it via `VerificationConfig(llm_judge=…)`.
The example in `examples/llm_judge_demo.py` walks through wiring one in.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional, Protocol, runtime_checkable

from elenchus.types import Claim, Evidence, Verdict

_log = logging.getLogger("elenchus.judges")


@runtime_checkable
class Judge(Protocol):
    """Pluggable Tier 2 judge.

    Implementations must accept a `Claim` and a list of candidate `Evidence`
    passages and return a `Verdict`. The verdict's `tier` field MUST be set
    to `"llm_judge"` (the verifier assumes this when it logs the escalation
    path).
    """

    def __call__(self, claim: Claim, evidence: List[Evidence]) -> Verdict: ...


@dataclass(frozen=True)
class FunctionJudge:
    """Wrap a plain function as a Judge.

    Useful when you have an existing function (e.g. one that calls OpenAI)
    and want to give it the `Judge` shape without subclassing anything.
    Optionally accepts a `name` so the structured log line identifies which
    judge ran.
    """

    fn: Callable[[Claim, List[Evidence]], Verdict]
    name: str = "function"

    def __call__(self, claim: Claim, evidence: List[Evidence]) -> Verdict:
        _log.debug(
            "judge_invoked",
            extra={"judge": self.name, "claim_id": claim.id, "n_evidence": len(evidence)},
        )
        verdict = self.fn(claim, evidence)
        # Defensive: if a caller forgets to set tier, force it so the log
        # and downstream tools see the right tier.
        if verdict.tier != "llm_judge":
            verdict = Verdict(
                claim=verdict.claim,
                label=verdict.label,
                confidence=verdict.confidence,
                tier="llm_judge",
                evidence=verdict.evidence,
                checked_at=verdict.checked_at,
            )
        return verdict


class EchoJudge:
    """Deterministic judge that always returns `supported` with high confidence.

    Used by tests as a stand-in for any external LLM. Never call it in
    production — it ignores the evidence entirely.
    """

    def __call__(self, claim: Claim, evidence: List[Evidence]) -> Verdict:
        return Verdict(
            claim=claim,
            label="supported",
            confidence=0.99,
            tier="llm_judge",
            evidence=evidence[0] if evidence else None,
            checked_at=datetime.now().astimezone(),
        )


@dataclass(frozen=True)
class KeywordOverlapJudge:
    """Deterministic, no-LLM judge based on word overlap between claim and evidence.

    Useful as a worked example of how to write a Tier 2 judge without any
    external dependencies, and as a baseline to compare real LLM judges
    against. The threshold is the fraction of claim tokens that must also
    appear in any single evidence passage for the claim to be `supported`.
    """

    threshold: float = 0.5
    name: str = "keyword_overlap"

    def __call__(self, claim: Claim, evidence: List[Evidence]) -> Verdict:
        if not evidence:
            return Verdict(
                claim=claim,
                label="unverifiable",
                confidence=0.0,
                tier="llm_judge",
                evidence=None,
                checked_at=datetime.now().astimezone(),
            )
        claim_tokens = set(_tokenize(claim.text))
        if not claim_tokens:
            return Verdict(
                claim=claim,
                label="unverifiable",
                confidence=0.0,
                tier="llm_judge",
                evidence=None,
                checked_at=datetime.now().astimezone(),
            )

        # Find the single evidence passage with the highest overlap.
        best: Optional[Evidence] = None
        best_overlap = 0.0
        for ev in evidence:
            ev_tokens = set(_tokenize(ev.text))
            if not ev_tokens:
                continue
            overlap = len(claim_tokens & ev_tokens) / len(claim_tokens | ev_tokens)
            if overlap > best_overlap:
                best_overlap = overlap
                best = ev

        if best is None or best_overlap < self.threshold:
            return Verdict(
                claim=claim,
                label="contradicted",
                confidence=min(1.0, 1.0 - best_overlap),
                tier="llm_judge",
                evidence=best,
                checked_at=datetime.now().astimezone(),
            )
        return Verdict(
            claim=claim,
            label="supported",
            confidence=min(1.0, best_overlap),
            tier="llm_judge",
            evidence=best,
            checked_at=datetime.now().astimezone(),
        )


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"\W+", text.lower()) if t]


__all__ = [
    "Judge",
    "FunctionJudge",
    "EchoJudge",
    "KeywordOverlapJudge",
]
