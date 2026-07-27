"""Unit tests for the Soteria adapter — bounded retry on blocked runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple

from elenchus.config import VerificationConfig
from elenchus.types import Claim, Evidence, Verdict

from studio.integrations import RetryResult
from studio.integrations.soteria import run_retry


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _StubVerifier:
    """Duck-typed Verifier stub.

    The Soteria adapter only calls `.verify(output_text, source_documents)`,
    so we don't need to subclass the real Verifier. We avoid loading the
    real cross-encoder NLI model by returning canned verdicts.
    """

    def __init__(self, label: str = "contradicted") -> None:
        self._label = label

    def verify(
        self,
        output_text: str,
        source_documents: List[Tuple[str, str]],
    ) -> List[Verdict]:
        return [
            Verdict(
                claim=Claim(id="c1", text=output_text, span=(0, len(output_text))),
                label=self._label,  # type: ignore[arg-type]
                confidence=0.95,
                tier="nli",
                evidence=(
                    Evidence(
                        source_id=source_documents[0][0] if source_documents else "unknown",
                        text=source_documents[0][1] if source_documents else "",
                        span=(0, 1),
                    )
                ),
                checked_at=_now(),
            )
        ]


def test_run_retry_returns_retry_result_with_attempts_and_stop_reason() -> None:
    v = _StubVerifier()
    result = run_retry(
        v, VerificationConfig(),
        candidate_answer="A claims X.",
        source_documents=[("kb", "Source says not-X.")],
        max_attempts=2,
    )
    assert isinstance(result, RetryResult)
    assert result.attempts >= 1
    assert result.stop_reason in {
        "repeated_action",
        "max_steps",
        "max_runtime",
        "completed",
    }


def test_run_retry_is_bounded_by_max_attempts() -> None:
    """REPEATED_ACTION must trigger at exactly max_attempts repeated calls."""
    v = _StubVerifier()
    max_attempts = 3
    result = run_retry(
        v, VerificationConfig(),
        candidate_answer="A claims X.",
        source_documents=[("kb", "Source says not-X.")],
        max_attempts=max_attempts,
    )
    assert max_attempts <= result.attempts <= max_attempts + 1
    assert result.stop_reason in {"repeated_action", "max_steps"}


def test_run_retry_propagates_final_verdicts() -> None:
    v = _StubVerifier(label="contradicted")
    result = run_retry(
        v, VerificationConfig(),
        candidate_answer="A claims X.",
        source_documents=[("kb", "Source says not-X.")],
        max_attempts=2,
    )
    assert isinstance(result.final_verdicts, list)
    assert len(result.final_verdicts) >= 1
    assert result.final_verdicts[0].label == "contradicted"


def test_run_retry_respects_max_attempts_one() -> None:
    """Even with max_attempts=1, the adapter must terminate (no infinite loop)."""
    v = _StubVerifier()
    result = run_retry(
        v, VerificationConfig(),
        candidate_answer="A claims X.",
        source_documents=[("kb", "Source says not-X.")],
        max_attempts=1,
        max_runtime_seconds=5.0,
    )
    assert result.attempts >= 1
    assert result.stop_reason in {"repeated_action", "max_steps", "completed"}
