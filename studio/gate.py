"""Output Gate — pure function over a run's verdicts.

Per Schema.md, gate evaluation is deterministic and ordered:

    1. `blocked`   if block_on_any_contradiction AND any verdict is contradicted.
    2. `flagged`   if unverifiable_count > flag_if_unverifiable_count_exceeds.
    3. `allowed`   otherwise.

This module is the only place this precedence lives. It is intentionally
side-effect-free so the policy can be tested in isolation, swapped per
project, and explained in one sentence.

Rule 2: GatePolicy is configuration, not hardcoded logic. The defaults
match Schema.md verbatim. Per-project overrides are passed to
`evaluate_gate` as the first argument — the gate itself has no project
state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal

from elenchus.types import Verdict


GateResult = Literal["allowed", "blocked", "flagged"]


@dataclass(frozen=True)
class GatePolicy:
    block_on_any_contradiction: bool = True
    flag_if_unverifiable_count_exceeds: int = 1


def evaluate_gate(policy: GatePolicy, verdicts: List[Verdict]) -> GateResult:
    """Evaluate the output gate for a set of verdicts.

    Pure function: no I/O, no logging, no side effects. The same
    (policy, verdicts) input always produces the same output, which is
    what makes the decision auditable.
    """
    if policy.block_on_any_contradiction and any(
        v.label == "contradicted" for v in verdicts
    ):
        return "blocked"

    unverifiable_count = sum(1 for v in verdicts if v.label == "unverifiable")
    if unverifiable_count > policy.flag_if_unverifiable_count_exceeds:
        return "flagged"

    return "allowed"


__all__ = ["GatePolicy", "evaluate_gate", "GateResult"]
