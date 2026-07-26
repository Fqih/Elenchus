"""Tests for Output Gate.

The gate is a pure function over verdicts per Schema.md precedence:
    1. blocked   if any contradiction AND block_on_any_contradiction
    2. flagged   if unverifiable_count > flag_if_unverifiable_count_exceeds
    3. allowed   otherwise

Rule 6: the gate lives in Studio, never in elenchus/. Rule 7: the gate
takes elenchus Verdict objects as input (the public API surface), not
internal types.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from elenchus.types import Claim, Verdict

from studio.gate import GatePolicy, evaluate_gate


# ---------- Helpers ----------------------------------------------------------


def _verdict(
    label: str,
    text: str = "x",
    confidence: float = 0.9,
    tier: str = "nli",
) -> Verdict:
    return Verdict(
        claim=Claim(id="c", text=text, span=(0, len(text))),
        label=label,  # type: ignore[arg-type]
        confidence=confidence,
        tier=tier,  # type: ignore[arg-type]
        evidence=None,
        checked_at=datetime.now(timezone.utc),
    )


# ---------- Precedence: blocked > flagged > allowed -------------------------


def test_gate_blocks_on_any_contradiction_when_policy_enabled() -> None:
    policy = GatePolicy(block_on_any_contradiction=True)
    verdicts = [_verdict("supported"), _verdict("contradicted")]
    assert evaluate_gate(policy, verdicts) == "blocked"


def test_gate_blocks_when_only_contradiction_is_present() -> None:
    policy = GatePolicy(block_on_any_contradiction=True)
    verdicts = [_verdict("contradicted")]
    assert evaluate_gate(policy, verdicts) == "blocked"


def test_gate_flagged_when_unverifiable_exceeds_threshold() -> None:
    policy = GatePolicy(
        block_on_any_contradiction=True,
        flag_if_unverifiable_count_exceeds=1,
    )
    verdicts = [
        _verdict("supported"),
        _verdict("unverifiable"),
        _verdict("unverifiable"),
    ]
    assert evaluate_gate(policy, verdicts) == "flagged"


def test_gate_allowed_when_no_contradiction_and_unverifiable_at_threshold() -> None:
    # Two unverifiable, threshold=2 → not strictly greater → allowed
    policy = GatePolicy(
        block_on_any_contradiction=True,
        flag_if_unverifiable_count_exceeds=2,
    )
    verdicts = [_verdict("supported"), _verdict("unverifiable")]
    assert evaluate_gate(policy, verdicts) == "allowed"


def test_gate_allowed_when_all_supported() -> None:
    policy = GatePolicy()
    verdicts = [_verdict("supported"), _verdict("supported")]
    assert evaluate_gate(policy, verdicts) == "allowed"


def test_gate_blocked_takes_precedence_over_flagged() -> None:
    # A contradiction AND >threshold unverifiable → must still be blocked.
    policy = GatePolicy(
        block_on_any_contradiction=True,
        flag_if_unverifiable_count_exceeds=0,
    )
    verdicts = [
        _verdict("contradicted"),
        _verdict("unverifiable"),
        _verdict("unverifiable"),
    ]
    assert evaluate_gate(policy, verdicts) == "blocked"


def test_gate_block_on_any_contradiction_disabled() -> None:
    policy = GatePolicy(
        block_on_any_contradiction=False,
        flag_if_unverifiable_count_exceeds=10,
    )
    verdicts = [_verdict("contradicted"), _verdict("unverifiable")]
    # Block path disabled + below flag threshold → allowed.
    assert evaluate_gate(policy, verdicts) == "allowed"


def test_gate_no_verdicts_returns_allowed() -> None:
    policy = GatePolicy()
    assert evaluate_gate(policy, []) == "allowed"


def test_gate_zero_unverifiable_threshold_makes_any_unverifiable_flag() -> None:
    policy = GatePolicy(
        block_on_any_contradiction=False,
        flag_if_unverifiable_count_exceeds=0,
    )
    verdicts = [_verdict("supported"), _verdict("unverifiable")]
    assert evaluate_gate(policy, verdicts) == "flagged"


def test_gate_threshold_is_strictly_greater_than() -> None:
    # Exactly at threshold should NOT trigger flag.
    policy = GatePolicy(
        block_on_any_contradiction=False,
        flag_if_unverifiable_count_exceeds=2,
    )
    verdicts = [_verdict("supported"), _verdict("unverifiable")]
    # 1 unverifiable, threshold 2 → strict > fails → allowed.
    assert evaluate_gate(policy, verdicts) == "allowed"


def test_gate_policy_is_frozen() -> None:
    # Per Schema.md dataclass(frozen=True).
    policy = GatePolicy()
    try:
        policy.block_on_any_contradiction = False  # type: ignore[misc]
    except Exception:  # FrozenInstanceError is a subclass of AttributeError
        return
    raise AssertionError("GatePolicy should be frozen")
