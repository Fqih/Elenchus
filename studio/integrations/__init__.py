"""Studio Phase 7 integrations.

Wires the Elenchus Studio backend to:
  - soteria-loop (Phase 7: bounded retry on blocked runs)
  - lethe-agent (Phase 7: write supported claims to per-project memory)

Both libraries live outside the Studio package. They are lazy-imported so
that the Studio server starts even when Phase 7 dependencies are missing;
the first attempt to use either integration raises Phase7DependencyError
with a clear install hint.

The elenchus/ library never imports soteria or lethe (Rule 6). The Studio
backend may import them via this module and the adapters it re-exports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from elenchus.types import Verdict


class Phase7DependencyError(RuntimeError):
    """Raised when a Phase 7 integration is requested but its dep is missing."""


# Lazy imports: the Studio server starts even without Phase 7 deps installed.
_run_retry_impl = None
_write_supported_claims_impl = None
_recall_run_claims_impl = None


def _ensure_soteria() -> None:
    global _run_retry_impl
    if _run_retry_impl is not None:
        return
    try:
        from studio.integrations import soteria as _soteria_mod  # noqa: WPS433
    except ImportError as exc:
        raise Phase7DependencyError(
            "Soteria is required for the blocked-path Phase 7 retry. "
            "Install with: pip install -e \".[phase7]\" (or pip install soteria-loop)."
        ) from exc
    _run_retry_impl = _soteria_mod.run_retry


def _ensure_lethe() -> None:
    global _write_supported_claims_impl, _recall_run_claims_impl
    if _write_supported_claims_impl is not None:
        return
    try:
        from studio.integrations import lethe as _lethe_mod  # noqa: WPS433
    except ImportError as exc:
        raise Phase7DependencyError(
            "Lethe is required for the allowed-path Phase 7 memory. "
            "Install with: pip install -e \".[phase7]\" (or pip install lethe-agent)."
        ) from exc
    _write_supported_claims_impl = _lethe_mod.write_supported_claims
    _recall_run_claims_impl = _lethe_mod.recall_run_claims


def run_retry(*args, **kwargs):
    """Lazy proxy to studio.integrations.soteria.run_retry."""
    _ensure_soteria()
    return _run_retry_impl(*args, **kwargs)


def write_supported_claims(*args, **kwargs):
    """Lazy proxy to studio.integrations.lethe.write_supported_claims."""
    _ensure_lethe()
    return _write_supported_claims_impl(*args, **kwargs)


def recall_run_claims(*args, **kwargs):
    """Lazy proxy to studio.integrations.lethe.recall_run_claims."""
    _ensure_lethe()
    return _recall_run_claims_impl(*args, **kwargs)


@dataclass
class RetryResult:
    """Result of a Phase 7 bounded Soteria retry.

    Fields:
      attempts: number of verifier invocations the Soteria loop performed.
      stop_reason: Soteria StopReason string (e.g. 'repeated_action').
      final_verdicts: verdicts from the last verify call inside the loop.
    """

    attempts: int
    stop_reason: str
    final_verdicts: List[Verdict]


__all__ = [
    "Phase7DependencyError",
    "RetryResult",
    "run_retry",
    "write_supported_claims",
    "recall_run_claims",
]
