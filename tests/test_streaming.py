"""StreamingVerifier tests — Phase 4 acceptance + Rule 5.

Rule 5 is the load-bearing test: feeding the same finished text through
both the batch `Verifier` and the streaming `StreamingVerifier` MUST produce
identical verdicts. They share one verification code path by design
(`Verifier.verify_claim`), so this isn't asserted — it's checked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from elenchus.config import VerificationConfig
from elenchus.streaming import StreamingVerifier
from elenchus.types import Verdict
from elenchus.verification_log import InMemoryVerificationLog
from elenchus.verifier import Verifier


# ---------- Fixtures --------------------------------------------------------


SOURCE_DOCS = [
    ("kb", "The Eiffel Tower in Paris attracts about 7 million visitors a year."),
]

CLEAN_TEXT = (
    "The Eiffel Tower is in Paris. "
    "Millions visit the Eiffel Tower each year. "
    "The Eiffel Tower is located on the Champs-Élysées."
)


def _stub_nli():
    """A deterministic NLI stub used by the equivalence test.

    Returns "supported" with high confidence when the claim appears in
    the source, "contradicted" with high confidence when the claim
    directly contradicts the source, and a small-gap ambiguous result
    otherwise.
    """

    class StubNli:
        def score(self, claim, evidence):
            import numpy as np

            if not evidence:
                return np.zeros((0, 3), dtype=np.float32)
            claim_text = claim.text.lower()
            src_text = evidence[0].text.lower()
            if claim_text in src_text or src_text in claim_text:
                return np.array([[0.02, 0.95, 0.03]])
            if "champs" in claim_text and "eiffel" in src_text:
                # claim about Champs-Élysées contradicts source about Eiffel
                return np.array([[0.92, 0.04, 0.04]])
            # anything else: small gap → would escalate
            return np.array([[0.42, 0.45, 0.13]])

        def verify(self, claim, evidence, checked_at=None):
            probs = self.score(claim, evidence)
            if len(probs) == 0:
                label = "unverifiable"
                conf = 0.0
            else:
                c, e, n = float(probs[0][0]), float(probs[0][1]), float(probs[0][2])
                if c >= 0.5 and c > e:
                    label, conf = "contradicted", c
                elif e >= 0.5 and e > c:
                    label, conf = "supported", e
                else:
                    label, conf = "unverifiable", n
            return Verdict(
                claim=claim,
                label=label,  # type: ignore[arg-type]
                confidence=conf,
                tier="nli",
                evidence=evidence[0] if evidence else None,
                checked_at=checked_at or datetime.now(timezone.utc),
            )

    return StubNli()


def _batch_verdicts(text: str, nli=None) -> List[Verdict]:
    log = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)
    v = Verifier(config=cfg, log=log, nli=nli or _stub_nli())
    return v.verify(output_text=text, source_documents=SOURCE_DOCS)


def _stream_verdicts(text: str, nli=None) -> List[Verdict]:
    log = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)
    nli = nli or _stub_nli()
    v = Verifier(config=cfg, log=log, nli=nli)
    sv = StreamingVerifier(verifier=v, log=log, source_documents=SOURCE_DOCS)
    sv.feed(text)
    sv.finish()
    return sv.verdicts()


# ---------- Rule 5: equivalence ---------------------------------------------


def test_streaming_and_batch_produce_identical_verdicts_for_clean_text() -> None:
    """Same finished text through both paths → same verdicts in same order."""
    batch = _batch_verdicts(CLEAN_TEXT)
    stream = _stream_verdicts(CLEAN_TEXT)
    assert _normalize(stream) == _normalize(batch)


def test_streaming_and_batch_produce_identical_verdicts_with_contradiction() -> None:
    text = (
        "The Eiffel Tower is in Paris. "
        "The Eiffel Tower is located on the Champs-Élysées."
    )
    batch = _batch_verdicts(text)
    stream = _stream_verdicts(text)
    assert _normalize(stream) == _normalize(batch)


def test_streaming_verifies_each_sentence_once_only() -> None:
    """The streaming path must not re-verify a completed sentence when a new
    sentence boundary is detected later."""
    log = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)
    nli = _stub_nli()
    v = Verifier(config=cfg, log=log, nli=nli)
    sv = StreamingVerifier(verifier=v, log=log, source_documents=SOURCE_DOCS)
    sv.feed(CLEAN_TEXT)
    sv.finish()
    assert len(sv.verdicts()) == 3
    assert len(log.entries()) == 3


def _normalize(verdicts: List[Verdict]):
    """Strip checked_at and id from verdicts for equality comparison."""
    return [
        (
            v.claim.span,
            v.claim.text,
            v.label,
            round(v.confidence, 6),
            v.tier,
            v.evidence.text if v.evidence else None,
        )
        for v in verdicts
    ]


def test_streaming_and_batch_share_decimal_sentence_boundaries() -> None:
    text = "Version 2.0 is current. Version 1.9 is obsolete."
    batch = _batch_verdicts(text)
    stream = _stream_verdicts(text)
    assert _normalize(stream) == _normalize(batch)
    assert [verdict.claim.text for verdict in stream] == [
        "Version 2.0 is current.",
        "Version 1.9 is obsolete.",
    ]


def test_streaming_waits_for_lookahead_before_terminal_period() -> None:
    log = InMemoryVerificationLog()
    verifier = Verifier(
        config=VerificationConfig(),
        log=log,
        nli=_stub_nli(),
    )
    stream = StreamingVerifier(
        verifier=verifier,
        log=log,
        source_documents=SOURCE_DOCS,
    )

    # The period may be a decimal separator, so it cannot be committed yet.
    assert stream.add_token("Version 2.") == []
    emitted = stream.add_token("0 is current. ")

    assert len(emitted) == 1
    assert emitted[0].claim.text == "Version 2.0 is current."


# ---------- Streaming behavior ---------------------------------------------


def test_streaming_returns_verdicts_in_order_as_tokens_arrive() -> None:
    log = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)
    nli = _stub_nli()
    v = Verifier(config=cfg, log=log, nli=nli)
    sv = StreamingVerifier(verifier=v, log=log, source_documents=SOURCE_DOCS)

    sv.add_token("The Eiffel Tower is in Paris. ")
    assert len(sv.verdicts()) == 1

    sv.add_token("Millions visit the Eiffel Tower each year. ")
    assert len(sv.verdicts()) == 2

    sv.add_token("The Eiffel Tower is located on the Champs-Élysées.")
    sv.finish()
    assert len(sv.verdicts()) == 3


def test_streaming_should_halt_returns_true_after_contradicted_claim() -> None:
    log = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)
    nli = _stub_nli()
    v = Verifier(config=cfg, log=log, nli=nli)
    sv = StreamingVerifier(verifier=v, log=log, source_documents=SOURCE_DOCS)

    sv.add_token("The Eiffel Tower is in Paris. ")
    assert sv.should_halt() is False

    sv.add_token("The Eiffel Tower is located on the Champs-Élysées.")
    sv.finish()
    assert sv.should_halt() is True


def test_streaming_finish_flushes_trailing_fragment_without_terminator() -> None:
    log = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)
    nli = _stub_nli()
    v = Verifier(config=cfg, log=log, nli=nli)
    sv = StreamingVerifier(verifier=v, log=log, source_documents=SOURCE_DOCS)
    # No terminating punctuation — finish() must still flush this as a claim.
    sv.add_token("Anne Frank died of typhus")
    sv.finish()
    assert len(sv.verdicts()) == 1
    assert "Anne Frank" in sv.verdicts()[0].claim.text


def test_streaming_logs_every_verdict_rule_4() -> None:
    log = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)
    nli = _stub_nli()
    v = Verifier(config=cfg, log=log, nli=nli)
    sv = StreamingVerifier(verifier=v, log=log, source_documents=SOURCE_DOCS)
    sv.feed(CLEAN_TEXT)
    sv.finish()
    # Rule 4: every check is logged.
    assert len(log.entries()) == 3


# ---------- Edge cases ------------------------------------------------------


def test_streaming_handles_empty_input() -> None:
    log = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)
    nli = _stub_nli()
    v = Verifier(config=cfg, log=log, nli=nli)
    sv = StreamingVerifier(verifier=v, log=log, source_documents=SOURCE_DOCS)
    sv.feed("")
    sv.finish()
    assert sv.verdicts() == []
    assert sv.should_halt() is False


def test_streaming_add_token_is_idempotent_after_finish() -> None:
    """After `finish()`, further add_token calls don't add new verdicts —
    the stream is closed."""
    log = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)
    nli = _stub_nli()
    v = Verifier(config=cfg, log=log, nli=nli)
    sv = StreamingVerifier(verifier=v, log=log, source_documents=SOURCE_DOCS)
    sv.add_token("Anne Frank died of typhus.")
    sv.finish()
    n = len(sv.verdicts())
    sv.add_token(" Something else.")
    sv.finish()
    assert len(sv.verdicts()) == n


def test_streaming_feed_concatenates_tokens_in_order() -> None:
    """`feed(text)` must call `add_token` per token and produce the same
    verdicts as `add_token` called manually with the same tokens."""
    log1 = InMemoryVerificationLog()
    log2 = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)
    nli = _stub_nli()
    v1 = Verifier(config=cfg, log=log1, nli=nli)
    v2 = Verifier(config=cfg, log=log2, nli=nli)

    sv_feed = StreamingVerifier(verifier=v1, log=log1, source_documents=SOURCE_DOCS)
    sv_manual = StreamingVerifier(verifier=v2, log=log2, source_documents=SOURCE_DOCS)
    tokens = ["The Eiffel Tower is in Paris. ", "Millions visit. ", "End."]
    sv_feed.feed("".join(tokens))
    sv_feed.finish()
    for tok in tokens:
        sv_manual.add_token(tok)
    sv_manual.finish()
    assert _normalize(sv_feed.verdicts()) == _normalize(sv_manual.verdicts())
