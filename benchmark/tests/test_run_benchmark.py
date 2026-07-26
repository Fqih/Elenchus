"""Tests for benchmark/run_benchmark.py — Phase 3 benchmark runner.

Tests the metric math and the stub-judge wiring. The full model-on-real-data
run is slow (CPU NLI forward passes) and is exercised by a separate script
the operator runs by hand, not by pytest.
"""

from __future__ import annotations

from typing import List

import pytest

from benchmark.run_benchmark import (
    BenchmarkRow,
    BenchmarkRun,
    METRIC_KEYS,
    cosine_predict,
    compute_metrics,
    keyword_judge,
    nli_only_predict,
    tiered_predict,
)


# ---------- Helpers ----------------------------------------------------------


def _row(
    claim: str,
    source: str,
    gold: str,
    *,
    response_id: str = "r",
    source_id: str = "s",
) -> BenchmarkRow:
    return BenchmarkRow(
        response_id=response_id,
        source_id=source_id,
        claim_text=claim,
        source_text=source,
        gold_label=gold,
    )


# ---------- compute_metrics --------------------------------------------------


def test_compute_metrics_perfect_predictions() -> None:
    golds = ["supported", "supported", "contradicted", "contradicted"]
    preds = ["supported", "supported", "contradicted", "contradicted"]
    m = compute_metrics(preds, golds, positive_label="contradicted")
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f1"] == 1.0
    assert m["true_positives"] == 2
    assert m["false_positives"] == 0
    assert m["false_negatives"] == 0


def test_compute_metrics_zero_recall_when_model_says_supported_always() -> None:
    golds = ["supported", "contradicted", "contradicted"]
    preds = ["supported", "supported", "supported"]
    m = compute_metrics(preds, golds, positive_label="contradicted")
    assert m["true_positives"] == 0
    assert m["false_negatives"] == 2
    assert m["recall"] == 0.0
    # 0 predicted positives → precision undefined; we report 0.0 not NaN
    assert m["precision"] == 0.0
    assert m["f1"] == 0.0


def test_compute_metrics_with_unverifiable_predictions() -> None:
    # Elenchus can emit "unverifiable" — treat it as "not contradicted"
    # (i.e. negative for the hallucination class). This matches the way
    # the benchmark reports to a developer: the system abstained.
    golds = ["supported", "contradicted", "contradicted", "supported"]
    preds = ["supported", "contradicted", "unverifiable", "supported"]
    m = compute_metrics(preds, golds, positive_label="contradicted")
    assert m["true_positives"] == 1
    assert m["false_negatives"] == 1  # the unverifiable that was actually contradicted
    assert m["true_negatives"] == 2
    assert m["false_positives"] == 0


def test_compute_metrics_can_detect_both_conflict_and_baseless_hallucinations() -> None:
    golds = ["supported", "contradicted", "unverifiable"]
    preds = ["supported", "unverifiable", "unverifiable"]
    m = compute_metrics(
        preds,
        golds,
        positive_labels={"contradicted", "unverifiable"},
    )
    assert m["true_positives"] == 2
    assert m["false_positives"] == 0
    assert m["recall"] == 1.0
    # Detection is perfect, while exact three-way accuracy still notices that
    # the conflict was classified as baseless.
    assert m["label_accuracy"] == pytest.approx(2 / 3)


def test_compute_metrics_handles_empty_input() -> None:
    m = compute_metrics([], [], positive_label="contradicted")
    assert m["true_positives"] == 0
    assert m["precision"] == 0.0
    assert m["recall"] == 0.0
    assert m["f1"] == 0.0


def test_compute_metrics_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="identical lengths"):
        compute_metrics(["supported"], [], positive_label="contradicted")


def test_compute_metrics_keys_are_stable() -> None:
    # RESULTS.md and any downstream tooling rely on these keys.
    assert set(METRIC_KEYS) == {
        "precision",
        "recall",
        "f1",
        "label_accuracy",
        "macro_f1",
        "true_positives",
        "false_positives",
        "true_negatives",
        "false_negatives",
        "positive_total",
        "supported_predicted_hallucinated",
        "escalation_count",
        "n_total",
    }


# ---------- Cosine baseline (stubbed) ---------------------------------------


def test_cosine_predict_supported_when_high_similarity(monkeypatch) -> None:
    # Stub the embedder to return known vectors.
    class StubEmbedder:
        def encode(self, texts):
            # Real sentence-transformers returns shape (n, dim) for a list of texts.
            return [_vec(t) for t in texts]

    def _vec(t):
        # Same vec if "Anne" in both texts (high sim), otherwise orthogonal.
        if "Anne" in t:
            return [1.0, 0.0]
        return [0.0, 1.0]

    row = _row(
        claim="Anne Frank died of typhus.",
        source="Anne Frank died of typhus in Bergen-Belsen.",
        gold="supported",
    )
    pred = cosine_predict(row, embedder=StubEmbedder(), threshold=0.5)
    assert pred == "supported"


def test_cosine_predict_contradicted_when_low_similarity() -> None:
    class StubEmbedder:
        def encode(self, texts):
            return [_vec(t) for t in texts]

    def _vec(t):
        if "Anne" in t:
            return [1.0, 0.0]
        return [0.0, 1.0]

    row = _row(
        claim="Berlin is the capital of France.",
        source="Anne Frank died of typhus in Bergen-Belsen.",
        gold="contradicted",
    )
    pred = cosine_predict(row, embedder=StubEmbedder(), threshold=0.5)
    # Cosine sim is 0 → below 0.5 threshold → contradicts
    assert pred == "contradicted"


# ---------- NLI-only baseline (stubbed) --------------------------------------


def test_nli_only_predict_returns_label_from_stub_verifier() -> None:
    class StubNli:
        def score(self, claim, evidence):
            import numpy as np

            return np.array([[0.99, 0.005, 0.005]])

        def verify(self, claim, evidence, checked_at=None):
            from elenchus.types import Claim, Verdict
            from datetime import datetime, timezone

            return Verdict(
                claim=Claim(id="c", text=claim.text, span=(0, len(claim.text))),
                label="contradicted",
                confidence=0.99,
                tier="nli",
                evidence=evidence[0] if evidence else None,
                checked_at=datetime.now(timezone.utc),
            )

    row = _row(
        claim="Anne Frank died in 2022.",
        source="Anne Frank died of typhus in 1945.",
        gold="contradicted",
    )
    pred = nli_only_predict(row, nli=StubNli())
    assert pred == "contradicted"


# ---------- Tiered predictor -------------------------------------------------


def test_tiered_predict_confident_call_skips_judge() -> None:
    """Tier 1 confident → uses NLI result, never calls judge."""
    judge_calls: List = []

    def judge(claim, evidence):
        judge_calls.append((claim, evidence))
        raise AssertionError("judge should NOT be called when Tier 1 is confident")

    class StubNli:
        def score(self, claim, evidence):
            import numpy as np

            # High entailment, low contradiction → large gap → confident
            return np.array([[0.01, 0.95, 0.04]])

        def verify(self, claim, evidence, checked_at=None):
            from elenchus.types import Claim, Verdict
            from datetime import datetime, timezone

            return Verdict(
                claim=Claim(id="c", text=claim.text, span=(0, len(claim.text))),
                label="supported",
                confidence=0.95,
                tier="nli",
                evidence=evidence[0] if evidence else None,
                checked_at=datetime.now(timezone.utc),
            )

    row = _row(
        claim="Anne Frank died of typhus.",
        source="Anne Frank died of typhus.",
        gold="supported",
    )
    pred, escalated = tiered_predict(
        row, nli=StubNli(), judge=judge, gap_threshold=0.15
    )
    assert pred == "supported"
    assert escalated is False
    assert judge_calls == []


def test_tiered_predict_ambiguous_calls_judge() -> None:
    """Tier 1 ambiguous (small gap) → calls judge."""
    from elenchus.types import Verdict
    from datetime import datetime, timezone

    judge_calls: List = []

    def judge(claim, evidence):
        judge_calls.append(claim)
        return Verdict(
            claim=claim,
            label="contradicted",
            confidence=0.7,
            tier="llm_judge",
            evidence=evidence[0] if evidence else None,
            checked_at=datetime.now(timezone.utc),
        )

    class StubNli:
        def score(self, claim, evidence):
            import numpy as np

            # Small gap → below threshold
            return np.array([[0.40, 0.45, 0.15]])

        def verdict_from_scores(self, claim, evidence, scores, checked_at=None):
            return Verdict(
                claim=claim,
                label="unverifiable",
                confidence=0.15,
                tier="nli",
                evidence=None,
                checked_at=checked_at or datetime.now(timezone.utc),
            )

    row = _row(
        claim="Margot died before Anne.",
        source="Margot died before Anne.",
        gold="contradicted",
    )
    pred, escalated = tiered_predict(
        row, nli=StubNli(), judge=judge, gap_threshold=0.15
    )
    assert pred == "contradicted"
    assert escalated is True
    assert len(judge_calls) == 1


def test_tiered_predict_no_judge_returns_unverifiable_on_ambiguity() -> None:
    """Rule 3: no judge configured + ambiguous → unverifiable."""

    class StubNli:
        def score(self, claim, evidence):
            import numpy as np

            return np.array([[0.42, 0.45, 0.13]])

        def verdict_from_scores(self, claim, evidence, scores, checked_at=None):
            from datetime import datetime, timezone
            from elenchus.types import Verdict

            return Verdict(
                claim=claim,
                label="unverifiable",
                confidence=0.13,
                tier="nli",
                evidence=None,
                checked_at=checked_at or datetime.now(timezone.utc),
            )

    row = _row(
        claim="Margot died before Anne.",
        source="Margot died before Anne.",
        gold="supported",
    )
    pred, escalated = tiered_predict(row, nli=StubNli(), judge=None, gap_threshold=0.15)
    assert pred == "unverifiable"
    assert escalated is False


def test_tiered_predict_matches_production_verifier_for_neutral_top_score() -> None:
    """The benchmark must not force a class the production verifier abstains on."""

    class StubNli:
        def score(self, claim, evidence):
            import numpy as np

            return np.array([[0.10, 0.40, 0.50]])

        def verify(self, claim, evidence, checked_at=None):
            from datetime import datetime, timezone
            from elenchus.types import Verdict

            return Verdict(
                claim=claim,
                label="unverifiable",
                confidence=0.50,
                tier="nli",
                evidence=None,
                checked_at=checked_at or datetime.now(timezone.utc),
            )

    row = _row(
        claim="A partially supported claim.",
        source="Some related evidence.",
        gold="supported",
    )
    pred, escalated = tiered_predict(
        row,
        nli=StubNli(),
        judge=None,
        gap_threshold=0.15,
    )
    assert pred == "unverifiable"
    assert escalated is False


# ---------- Keyword judge (used as the Tier-2 stand-in in the main run) -----


def test_keyword_judge_flags_year_mismatch() -> None:
    # Year in claim not in source → contradicted.
    from elenchus.types import Claim, Evidence

    claim = Claim(id="c", text="Anne Frank died in 2022.", span=(0, 24))
    evidence = [
        Evidence(source_id="s", text="Anne Frank died of typhus in 1945.", span=(0, 35))
    ]
    v = keyword_judge(claim, evidence)
    assert v.label == "contradicted"


def test_keyword_judge_says_supported_when_no_mismatch() -> None:
    from elenchus.types import Claim, Evidence

    claim = Claim(id="c", text="Anne Frank died of typhus.", span=(0, 26))
    evidence = [
        Evidence(
            source_id="s",
            text="Anne Frank died of typhus in Bergen-Belsen.",
            span=(0, 44),
        )
    ]
    v = keyword_judge(claim, evidence)
    assert v.label == "supported"


def test_keyword_judge_abstains_when_no_numbers() -> None:
    from elenchus.types import Claim, Evidence

    claim = Claim(id="c", text="Anne Frank was a teenager.", span=(0, 26))
    evidence = [
        Evidence(source_id="s", text="Anne Frank was fifteen years old.", span=(0, 34))
    ]
    v = keyword_judge(claim, evidence)
    assert v.label == "unverifiable"


# ---------- BenchmarkRun ---------------------------------------------------


def test_benchmark_run_serializes_to_dict() -> None:
    run = BenchmarkRun(
        seed=1,
        n_total=10,
        precision=0.8,
        recall=0.7,
        f1=0.74,
        label_accuracy=0.8,
        macro_f1=0.72,
        true_positives=4,
        false_positives=1,
        true_negatives=4,
        false_negatives=1,
        positive_total=5,
        supported_predicted_hallucinated=1,
        escalation_count=2,
    )
    d = run.to_dict()
    assert d["seed"] == 1
    assert d["f1"] == 0.74
    assert d["escalation_count"] == 2
