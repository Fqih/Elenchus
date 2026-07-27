"""Soteria adapter for the Studio Phase 7 blocked-path retry.

Builds a Soteria AgentRuntime whose sole tool re-invokes the existing
Verifier on the same candidate answer. Soteria's LoopPolicy bounds the
retry (REPEATED_ACTION exits after `max_attempts` repeated calls;
MAX_RUNTIME caps wall-clock at 30s; MAX_STEPS caps total steps). The
agent uses Soteria's FakeProvider because Rule 4 forbids candidate
generation in Studio — the agent never invents text, it only re-runs
the verifier under Soteria's bounds.

Public entry point:
  run_retry(verifier, config, *, candidate_answer, source_documents,
            candidate_question, max_attempts=2) -> RetryResult
"""

from __future__ import annotations

import asyncio
import os
from typing import Callable, List, Optional, Tuple

from elenchus.config import VerificationConfig
from elenchus.types import Verdict
from elenchus.verifier import Verifier
from pydantic import BaseModel

from soteria_loop import (
    AgentRuntime,
    FunctionTool,
    ModelResponse,
    ToolCall,
    TokenUsage,
)
from soteria_loop.policies import LoopPolicy
from soteria_loop.providers.fake import FakeProvider
from soteria_loop.storage.memory import InMemoryEventStore
from soteria_loop.tools import ToolRegistry

from studio.integrations import RetryResult


class _VerifyArgs(BaseModel):
    """Empty arguments model — the verify tool receives no params.

    The runtime always invokes it with the same candidate inputs, which
    are captured in the closure of the tool function. Keeping the
    arguments model empty ensures the FakeProvider's empty-arguments
    tool_call satisfies FunctionTool's validation.
    """


# Tool name used both for the script and the FunctionTool registration.
_VERIFY_TOOL_NAME = "verify_candidate"


def _script_for_attempts(max_attempts: int) -> List[ModelResponse]:
    """Build a FakeProvider script of repeated tool-call responses.

    Each script entry asks the runtime to call `verify_candidate`. After
    `max_attempts` repeated calls, Soteria's REPEATED_ACTION policy
    exits the loop. We add one final tool-call entry to ensure the
    repeated-action limit trips before the script is exhausted.
    """
    items: List[ModelResponse] = []
    for i in range(max_attempts + 1):
        items.append(
            ModelResponse(
                tool_call=ToolCall(
                    tool_call_id=f"verify-{i}",
                    name=_VERIFY_TOOL_NAME,
                    arguments={},
                ),
                usage=TokenUsage(input_tokens=1, output_tokens=1),
            )
        )
    return items


def _make_verify_tool(
    verifier: Verifier,
    *,
    candidate_answer: str,
    source_documents: List[Tuple[str, str]],
) -> Callable[[_VerifyArgs], dict]:
    """Wrap verifier.verify as a Soteria FunctionTool callable.

    The returned callable takes the parsed empty Pydantic arguments and
    returns a JSON-serializable dict with the verdicts. Same inputs
    every call — the agent re-verifies the same candidate, so the
    behavior is deterministic across the loop.
    """

    def _tool(_args: _VerifyArgs) -> dict:
        verdicts = verifier.verify(
            output_text=candidate_answer,
            source_documents=source_documents,
        )
        return {
            "verdicts": [
                {
                    "claim_id": v.claim.id,
                    "label": v.label,
                    "confidence": v.confidence,
                }
                for v in verdicts
            ],
        }

    return _tool


def _build_runtime(
    verifier: Verifier,
    *,
    candidate_answer: str,
    source_documents: List[Tuple[str, str]],
    max_attempts: int,
    max_runtime_seconds: float,
) -> AgentRuntime:
    verify_fn = _make_verify_tool(
        verifier,
        candidate_answer=candidate_answer,
        source_documents=source_documents,
    )
    tool = FunctionTool(
        name=_VERIFY_TOOL_NAME,
        description="Re-run Elenchus verification on the same candidate.",
        arguments_model=_VerifyArgs,
        function=verify_fn,
    )
    registry = ToolRegistry([tool])
    provider = FakeProvider(_script_for_attempts(max_attempts))
    policy = LoopPolicy(
        repeated_action_limit=max_attempts,
        max_steps=max_attempts + 1,
        max_runtime_seconds=max_runtime_seconds,
        consecutive_error_limit=max(1, max_attempts),
    )
    return AgentRuntime(
        provider=provider,
        tools=[tool],
        policy=policy,
        event_store=InMemoryEventStore(),
    )


def run_retry(
    verifier: Verifier,
    config: VerificationConfig,
    *,
    candidate_answer: str,
    source_documents: List[Tuple[str, str]],
    max_attempts: Optional[int] = None,
    max_runtime_seconds: float = 30.0,
) -> RetryResult:
    """Run a bounded Soteria retry over the verifier.

    Args:
      verifier: the existing Studio Verifier instance.
      config: kept for future per-call overrides; currently unused.
      candidate_answer: the text that originally triggered 'blocked'.
      source_documents: list of (source_id, content) tuples — same as /checks.
      max_attempts: override the policy's repeated_action_limit. Defaults
        to env ELENCHUS_PHASE7_MAX_ATTEMPTS or 2.
      max_runtime_seconds: wall-clock cap. Default 30s.

    Returns:
      RetryResult(attempts, stop_reason, final_verdicts).
    """
    del config  # currently unused; reserved for per-call overrides
    if max_attempts is None:
        max_attempts = int(os.environ.get("ELENCHUS_PHASE7_MAX_ATTEMPTS", "2"))
    runtime = _build_runtime(
        verifier,
        candidate_answer=candidate_answer,
        source_documents=source_documents,
        max_attempts=max_attempts,
        max_runtime_seconds=max_runtime_seconds,
    )

    async def _drive() -> tuple[int, str, List[Verdict]]:
        result = await runtime.run(
            "Phase 7 retry: re-verify candidate under Soteria bounds."
        )
        # Re-run the verifier once more on the way out so the caller has
        # the final, fresh verdicts (Soteria's tool result is wrapped,
        # not the raw Verdict list).
        final_verdicts = verifier.verify(
            output_text=candidate_answer,
            source_documents=source_documents,
        )
        # Count verifier invocations: the runtime recorded each request
        # via the provider. The FakeProvider exposes its request log.
        try:
            attempts = len(runtime.provider.requests)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            attempts = max_attempts
        # Map Soteria's terminal state to a stop reason string.
        try:
            stop_reason = result.stop_reason.value  # type: ignore[union-attr]
        except Exception:  # pragma: no cover
            stop_reason = "internal_error"
        return attempts, stop_reason, final_verdicts

    attempts, stop_reason, final_verdicts = asyncio.run(_drive())
    return RetryResult(attempts=attempts, stop_reason=stop_reason, final_verdicts=final_verdicts)


__all__ = ["run_retry", "RetryResult"]
