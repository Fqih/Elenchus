"""Phase 13: streaming verifier — claim-by-claim yielding.

The streaming variant of `Verifier.verify` must yield verdicts one at a
time in the same order and with the same labels as the batch call.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import numpy as np

from elenchus.config import VerificationConfig
from elenchus.types import Verdict
from elenchus.verification_log import InMemoryVerificationLog
from elenchus.verifier import Verifier


def _stub_nli() -> MagicMock:
    nli = MagicMock(spec=["score", "verify", "verdict_from_scores"])
    nli.score.return_value = np.array([[0.05, 0.90, 0.05]])

    def from_scores(claim, evidence, scores, checked_at=None):
        return Verdict(
            claim=claim,
            label="supported",
            confidence=0.90,
            tier="nli",
            evidence=evidence[0] if evidence else None,
            checked_at=checked_at or datetime.now().astimezone(),
        )

    nli.verdict_from_scores.side_effect = from_scores
    return nli


def test_stream_verdicts_yields_same_results_as_batch() -> None:
    """Streaming yields each verdict in order; identical to batch."""
    cfg = VerificationConfig()
    log = InMemoryVerificationLog()
    verifier = Verifier(config=cfg, log=log, nli=_stub_nli())

    output_text = (
        "Standard shipping takes 3 to 5 days. "
        "Returns within 30 days. "
        "Contact support@example.com for help."
    )
    sources = [("kb", "Shipping policy: standard shipping takes 3 to 5 days.")]

    batch = verifier.verify(output_text=output_text, source_documents=sources)
    streamed = list(verifier.stream_verdicts(output_text=output_text, source_documents=sources))

    assert len(batch) == len(streamed) == 3
    for b, s in zip(batch, streamed):
        assert b.claim.text == s.claim.text
        assert b.label == s.label
        assert b.tier == s.tier


def test_stream_verdicts_logs_each_verdict_before_raising_stopiteration() -> None:
    """Streaming logs the verdict at the moment it's yielded (Rule 4)."""
    cfg = VerificationConfig()
    log = InMemoryVerificationLog()
    verifier = Verifier(config=cfg, log=log, nli=_stub_nli())

    sources = [("kb", "Standard shipping takes 3 to 5 days.")]
    output_text = "Standard shipping takes 3 to 5 days. Returns within 30 days."

    it = verifier.stream_verdicts(output_text=output_text, source_documents=sources)
    first = next(it)
    # The log should already have the first verdict by the time we yield it.
    assert len(log.entries()) == 1
    assert log.entries()[0].verdict.claim.text == first.claim.text

    # Drain the rest.
    for _ in it:
        pass
    assert len(log.entries()) == 2


def test_stream_verdicts_empty_output_yields_nothing() -> None:
    """No claims → empty stream (no errors)."""
    cfg = VerificationConfig()
    log = InMemoryVerificationLog()
    verifier = Verifier(config=cfg, log=log, nli=_stub_nli())

    streamed = list(verifier.stream_verdicts(output_text="", source_documents=[]))
    assert streamed == []
