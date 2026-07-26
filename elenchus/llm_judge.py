"""Tier 2: optional LLM judge.

The judge is a plain `Callable[[Claim, list[Evidence]], Verdict]` injected via
`VerificationConfig.llm_judge`. Rule 3 applies here directly: no configured
judge → ambiguous resolves to `unverifiable`, never a forced guess. The
helper below is the single place that decides whether the judge runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, List, Optional

from elenchus.types import Claim, Evidence, Verdict


def invoke_judge(
    judge: Optional[Callable[[Claim, List[Evidence]], Verdict]],
    claim: Claim,
    evidence: List[Evidence],
) -> Verdict:
    """Call `judge(claim, evidence)` if one is configured.

    If `judge is None`, return an `unverifiable` Verdict with confidence 0 —
    Rule 3. The fallback carries the same `claim` through so it slots into
    the rest of the pipeline without special casing.
    """
    if judge is None:
        return Verdict(
            claim=claim,
            label="unverifiable",
            confidence=0.0,
            tier="nli",  # the verdict came out of the NLI gap analysis
            evidence=None,
            checked_at=datetime.now().astimezone(),
        )
    return judge(claim, evidence)


__all__ = ["invoke_judge"]
