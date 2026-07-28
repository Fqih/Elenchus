"""Batch Verifier — orchestrator.

Two-tier verification pipeline:

    extract claims → retrieve evidence → score via NLI (Tier 1)
        │                                       │
        │                          ┌─ gap < threshold (ambiguous) ─┐
        │                          ↓                                ↓
        └─ log every verdict (Rule 4)    if judge configured: invoke Tier 2
                                          else: unverifiable (Rule 3)

Phase 1 had Tier 1 only. Phase 2 adds the confidence-gap escalation above.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterator, List, Optional, Sequence, Tuple

from elenchus.claim_extractor import extract_claims
from elenchus.config import VerificationConfig
from elenchus.evidence_retriever import retrieve_evidence
from elenchus.llm_judge import invoke_judge
from elenchus.nli_verifier import NliVerifier
from elenchus.types import Claim, Evidence, Verdict
from elenchus.verification_log import VerificationLog


class Verifier:
    """Orchestrates per-claim verification with optional Tier-2 escalation."""

    def __init__(
        self,
        config: VerificationConfig,
        log: VerificationLog,
        nli: Optional[NliVerifier] = None,
    ) -> None:
        self._config = config
        self._log = log
        self._nli = nli if nli is not None else NliVerifier(config=config)

    def verify(
        self,
        output_text: str,
        source_documents: Sequence[Tuple[str, str]],
    ) -> List[Verdict]:
        """Verify every claim in `output_text` against `source_documents`."""
        claims = extract_claims(output_text)
        return [self.verify_claim(claim, source_documents) for claim in claims]

    def stream_verdicts(
        self,
        output_text: str,
        source_documents: Sequence[Tuple[str, str]],
    ) -> Iterator[Verdict]:
        """Yield each verdict as soon as it's produced.

        This is the streaming variant of `verify`. The verdict sequence is
        identical to `verify(output_text, source_documents)` for the same
        inputs — same claims, same Tier-1 / Tier-2 routing, same log writes
        — but the caller receives each Verdict the moment it is decided.

        Used by the studio API's SSE `/checks/stream` endpoint so a long
        verification run can stream progress to the UI claim-by-claim
        instead of blocking until the full batch completes.

        Rule 5: `StreamingVerifier` and `Verifier` produce identical verdicts
        on the same finished text. The streaming batch path here is the same
        single-claim pipeline as `verify_claim`, called one at a time.
        """
        claims = extract_claims(output_text)
        for claim in claims:
            yield self.verify_claim(claim, source_documents)

    def verify_claim(
        self,
        claim: Claim,
        source_documents: Sequence[Tuple[str, str]],
    ) -> Verdict:
        """Verify a single `Claim` against `source_documents`.

        Public alias for the per-claim pipeline shared by batch and streaming
        (Rule 5). StreamingVerifier calls this directly for each completed
        sentence; the batch `verify` calls it for every claim extracted from
        the full output. Both paths return identical verdicts for identical
        (claim, source) inputs because the call is the same call.
        """
        return self._verify_one(claim, source_documents)

    def _verify_one(
        self,
        claim: Claim,
        source_documents: Sequence[Tuple[str, str]],
    ) -> Verdict:
        evidence = retrieve_evidence(
            claim=claim,
            source_documents=source_documents,
            config=self._config,
        )

        scores = self._nli.score(claim, evidence)
        # Build Tier 1's actual verdict first, reusing the score matrix when
        # supported. Routing is then based on that selected evidence passage,
        # rather than comparing maxima from unrelated passages.
        from_scores = getattr(self._nli, "verdict_from_scores", None)
        if callable(from_scores):
            tier1_verdict = from_scores(
                claim=claim,
                evidence=evidence,
                scores=scores,
                checked_at=datetime.now().astimezone(),
            )
        else:
            tier1_verdict = self._nli.verify(
                claim=claim,
                evidence=evidence,
                checked_at=datetime.now().astimezone(),
            )

        should_escalate = self._should_escalate(
            verdict=tier1_verdict,
            evidence=evidence,
            scores=scores,
        )
        if should_escalate:
            verdict = invoke_judge(self._config.llm_judge, claim, evidence)
        else:
            verdict = tier1_verdict

        # Log before returning — Rule 4.
        self._log.append(verdict)
        return verdict

    def _should_escalate(
        self,
        verdict: Verdict,
        evidence: List[Evidence],
        scores,
    ) -> bool:
        """Return whether Tier 1's selected passage is genuinely ambiguous."""
        if not evidence or scores is None or len(scores) == 0:
            return False

        if (
            verdict.label == "unverifiable"
            and self._config.nli_decision_threshold > 0.0
        ):
            return True
        if verdict.label not in {"supported", "contradicted"}:
            return False

        try:
            selected_idx = evidence.index(verdict.evidence)
        except ValueError:
            # An injected verifier may construct an equivalent-looking
            # evidence object that is not one of the candidates. Confidence is
            # still a safe routing signal in that case.
            return verdict.confidence < self._config.nli_decision_threshold

        contradiction, entailment, neutral = (
            float(value) for value in scores[selected_idx]
        )
        selected = entailment if verdict.label == "supported" else contradiction
        runner_up = max(
            contradiction if verdict.label == "supported" else entailment,
            neutral,
        )
        gap = selected - runner_up
        return selected < self._config.nli_decision_threshold or (
            self._config.confidence_gap_threshold > 0.0
            and gap < self._config.confidence_gap_threshold
        )


__all__ = ["Verifier"]
