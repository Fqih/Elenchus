"""Streaming verifier — Phase 4.

The streaming verifier takes a token stream and runs each completed
sentence through the same `Verifier.verify_claim` the batch path uses
(Rule 5: one verification code path). When a `contradicted` claim is
detected mid-stream, `should_halt()` flips to True so the caller can
cut the response.

The streaming path is a thin wrapper around the batch one — it does
not duplicate any verification logic. The contract:

    - StreamingVerifier holds a reference to a `Verifier`.
    - It buffers tokens, accumulates them into sentences using the same
      `extract_claims` the batch path uses (so spans match).
    - For each completed sentence it calls `verifier.verify_claim(claim, ...)`.
    - `finish()` flushes any trailing fragment without a terminator.

Because both paths call the same `verify_claim`, identical inputs
produce identical verdicts — proven by `tests/test_streaming.py`.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from elenchus.claim_extractor import extract_claims, find_sentence_boundary
from elenchus.types import Verdict
from elenchus.verification_log import VerificationLog
from elenchus.verifier import Verifier


class StreamingVerifier:
    """Token-stream wrapper around the batch `Verifier`.

    Use `add_token(...)` (or `feed(text)` for convenience) as the model
    emits text. After each completed sentence, the underlying
    `Verifier.verify_claim` is invoked and the resulting verdict is
    appended to the verdicts list and to the log (Rule 4).
    """

    def __init__(
        self,
        verifier: Verifier,
        log: VerificationLog,
        source_documents: Optional[Sequence[Tuple[str, str]]] = None,
    ) -> None:
        self._verifier = verifier
        self._log = log
        # `source_documents` may be set up front (typical) or via
        # `set_source_documents()` before any token arrives.
        self._source_documents: Optional[Sequence[Tuple[str, str]]] = source_documents

        # All text ever fed in, in order. We re-run `extract_claims` on a
        # prefix of this so the claim spans match what batch verification
        # would produce on the same finished text (Rule 5).
        self._absolute_text: str = ""

        # The slice of `_absolute_text` that hasn't yet been verified
        # (no sentence boundary reached, or trailing fragment after the
        # last terminator).
        self._verified_length: int = 0

        self._verdicts: List[Verdict] = []
        self._halted: bool = False
        self._closed: bool = False

    # ---- Source-doc binding -------------------------------------------------

    def set_source_documents(self, source_documents: Sequence[Tuple[str, str]]) -> None:
        """Set or replace the source documents after construction."""
        self._source_documents = source_documents

    # ---- Public streaming API ----------------------------------------------

    def add_token(self, token: str) -> List[Verdict]:
        """Append `token` to the stream; emit any verdicts produced.

        Returns the list of verdicts produced by THIS call (zero or more).
        """
        if self._closed:
            return []
        if self._source_documents is None:
            raise RuntimeError(
                "StreamingVerifier: source_documents must be set before add_token"
            )

        self._absolute_text += token
        return self._drain_completed_sentences(flush_trailing=False)

    def feed(self, text: str) -> List[Verdict]:
        """Convenience: feed an arbitrary string as a single token.

        Tokenization is the caller's responsibility (this is a thin
        wrapper, not an LLM client). Equivalent to `add_token(text)`.
        """
        return self.add_token(text)

    def finish(self) -> List[Verdict]:
        """Flush any trailing fragment without a sentence terminator.

        After `finish()` the stream is closed; further add_token calls
        are no-ops.
        """
        if self._closed:
            return []
        new_verdicts = self._drain_completed_sentences(flush_trailing=True)
        self._closed = True
        return new_verdicts

    def verdicts(self) -> List[Verdict]:
        return list(self._verdicts)

    def should_halt(self) -> bool:
        """True iff at least one verdict so far is `contradicted`."""
        return self._halted

    # ---- Internals ----------------------------------------------------------

    def _drain_completed_sentences(self, flush_trailing: bool) -> List[Verdict]:
        """Find the next sentence-ending position in the unverified tail,
        extract its claim via `extract_claims` on the prefix, and verify.

        Loops until no more completed sentences are available (or one was
        verified, depending on flush mode).
        """
        out: List[Verdict] = []
        while True:
            tail = self._absolute_text[self._verified_length :]
            sentence_end_in_tail = find_sentence_boundary(
                tail,
                final=flush_trailing,
            )
            if sentence_end_in_tail is None:
                if flush_trailing and tail.strip():
                    sentence_end_in_tail = len(tail)
                else:
                    break

            # Build the prefix that ends at this sentence and let
            # `extract_claims` figure out the spans. The last claim in
            # the prefix is the one we want.
            prefix = self._absolute_text[: self._verified_length + sentence_end_in_tail]
            claims = extract_claims(prefix)
            if not claims:
                # Shouldn't happen if the boundary is on real punctuation.
                # Advance past it to avoid an infinite loop.
                self._verified_length += sentence_end_in_tail
                continue
            claim = claims[-1]
            # Make sure the claim text actually ends at our boundary
            # (extract_claims strips trailing whitespace). Allow either
            # exact match or a tiny lead.
            assert claim.span[1] <= self._verified_length + sentence_end_in_tail, (
                claim.span,
                self._verified_length,
                sentence_end_in_tail,
            )
            verdict = self._verifier.verify_claim(claim, self._source_documents)
            self._verdicts.append(verdict)
            if verdict.label == "contradicted":
                self._halted = True
            out.append(verdict)
            # Advance past everything we just verified.
            self._verified_length += sentence_end_in_tail
        return out


__all__ = ["StreamingVerifier"]
