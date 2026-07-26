"""Single source of truth for tunable verification behavior (Rule 1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from elenchus.verifier import Claim, Evidence, Verdict


@dataclass(frozen=True)
class VerificationConfig:
    """Tunables for the verification pipeline.

    Defaults are exact per .context/Schema.md. Nothing elsewhere in the library
    is allowed to introduce magic numbers — Rule 1.
    """

    confidence_gap_threshold: float = 0.15  # tier-1 -> tier-2 escalation trigger
    nli_decision_threshold: float = 0.50
    nli_model_name: str = "cross-encoder/nli-deberta-v3-base"
    max_evidence_passages_per_claim: int = 5
    max_evidence_window_chunks: int = 4
    llm_judge: Optional[Callable[["Claim", list["Evidence"]], "Verdict"]] = None


# Forward-import avoidance: keep the Callable signature usable from static
# checkers without inducing a runtime import cycle through verifier.py.
__all__ = ["VerificationConfig"]
