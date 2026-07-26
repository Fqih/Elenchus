"""Tier 1: local cross-encoder NLI verification.

Loads a sentence-transformers CrossEncoder (default `cross-encoder/nli-deberta-v3-base`)
and produces `Verdict` objects from (evidence premise, claim hypothesis) pairs. Label index
ordering is `0=contradiction`, `1=entailment`, `2=neutral` per HuggingFace's
NLI convention — confirmed at load time against the model's `id2label` so a
different model with a different ordering can't silently mislabel verdicts.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List

import torch
from sentence_transformers import CrossEncoder

from elenchus.config import VerificationConfig
from elenchus.evidence_retriever import lexical_relevance
from elenchus.types import Claim, Evidence, Verdict

if TYPE_CHECKING:
    import numpy as np

# Index → label string for cross-encoder/nli-deberta-v3-base.
# Validated at instantiation; will raise if a different model uses a different
# mapping, rather than silently producing wrong verdicts.
_EXPECTED_LABELS = {0: "contradiction", 1: "entailment", 2: "neutral"}


class NliVerifier:
    """Verifies `Claim` against candidate `Evidence` using a local NLI model."""

    def __init__(self, config: VerificationConfig) -> None:
        self._config = config
        # sentence-transformers 5.x calls `activation_fn(scores)` with no args,
        # so we wrap torch.softmax with a dim. Required for Verdict.confidence
        # to be a probability on [0, 1].
        self._model = CrossEncoder(
            config.nli_model_name,
            activation_fn=lambda t: torch.softmax(t, dim=-1),
        )
        labels = {
            int(k): v.lower() for k, v in self._model.model.config.id2label.items()
        }
        if labels != _EXPECTED_LABELS:
            raise ValueError(
                f"Unexpected NLI label layout: {labels}. "
                f"Cross-encoder NLI index ordering must be {sorted(_EXPECTED_LABELS.values())}."
            )

    def score(
        self,
        claim: Claim,
        evidence: List[Evidence],
    ) -> "np.ndarray":
        """Return (n_evidence, 3) softmax probability matrix.

        Column order is `[contradiction, entailment, neutral]` per the model's
        `id2label`. The verifier uses this raw matrix to compute the
        confidence gap that drives escalation.
        """
        import numpy as np

        if not evidence:
            # (0, 3) — no evidence to score
            return np.zeros((0, 3), dtype=np.float32)
        # NLI is directional: sentence A is the premise and sentence B is the
        # hypothesis. The source evidence is therefore the premise from which
        # the generated claim must follow. Reversing this order causes valid
        # generalisations (specific source -> broader claim) to be labelled
        # neutral.
        pairs = [(e.text, claim.text) for e in evidence]
        return self._model.predict(pairs, convert_to_numpy=True)

    def verify(
        self,
        claim: Claim,
        evidence: List[Evidence],
        checked_at: datetime | None = None,
    ) -> Verdict:
        """Score evidence-premise/claim-hypothesis pairs and return one Verdict.

        Candidate selection combines raw NLI signal with deterministic lexical
        relevance; the reported confidence remains the raw model probability.

        If `evidence` is empty, returns unverifiable with confidence 0.
        """
        if not evidence:
            return Verdict(
                claim=claim,
                label="unverifiable",
                confidence=0.0,
                tier="nli",
                evidence=None,
                checked_at=checked_at or datetime.now().astimezone(),
            )

        probs = self.score(claim, evidence)
        return self.verdict_from_scores(
            claim=claim,
            evidence=evidence,
            scores=probs,
            checked_at=checked_at,
        )

    def verdict_from_scores(
        self,
        claim: Claim,
        evidence: List[Evidence],
        scores,
        checked_at: datetime | None = None,
    ) -> Verdict:
        """Build a verdict from an already-computed NLI score matrix.

        ``Verifier`` uses this method so confidence routing and final verdict
        construction share a single model forward pass. ``verify`` remains the
        convenient standalone API and delegates here after scoring.
        """
        if not evidence or scores is None or len(scores) == 0:
            return Verdict(
                claim=claim,
                label="unverifiable",
                confidence=0.0,
                tier="nli",
                evidence=None,
                checked_at=checked_at or datetime.now().astimezone(),
            )

        # Choose the strongest decision after applying the retriever's local
        # relevance as a ranking prior. Raw NLI confidence alone can assign an
        # unrelated but structurally similar passage a slightly stronger
        # contradiction score than an exact supporting sentence. Relevance is
        # used only to select the passage; Verdict.confidence remains the raw
        # model probability.
        best_utility = -1.0
        best_probability = 0.0
        best_label = "unverifiable"
        best_idx = -1
        max_neutral = 0.0
        for i, p in enumerate(scores):
            c, e, n = float(p[0]), float(p[1]), float(p[2])
            if n > max_neutral:
                max_neutral = n
            relevance_multiplier = 1.0 + lexical_relevance(
                claim.text,
                evidence[i].text,
            )
            if e * relevance_multiplier > best_utility:
                best_utility = e * relevance_multiplier
                best_probability = e
                best_label = "supported"
                best_idx = i
            if c * relevance_multiplier > best_utility:
                best_utility = c * relevance_multiplier
                best_probability = c
                best_label = "contradicted"
                best_idx = i

        threshold = self._config.nli_decision_threshold
        if best_probability < threshold:
            # No passage moved the model enough to call it either way.
            label = "unverifiable"
            conf = max_neutral
            chosen_idx = -1  # evidence-less for true ambiguity
        else:
            label = best_label
            conf = best_probability
            chosen_idx = best_idx

        return Verdict(
            claim=claim,
            label=label,  # type: ignore[arg-type]
            confidence=float(conf),
            tier="nli",
            evidence=evidence[chosen_idx] if chosen_idx >= 0 else None,
            checked_at=checked_at or datetime.now().astimezone(),
        )


__all__ = ["NliVerifier"]
