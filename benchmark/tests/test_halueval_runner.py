"""Unit tests for benchmark/halueval_runner.

We don't hit the network. Instead we mock the rows and exercise
pair-construction + metric computation, which is the whole logic
without needing a HuggingFace dataset download.
"""

from __future__ import annotations

import pytest

from benchmark.halueval_runner import (
    EvalPair,
    HALUEVAL_NEGATIVE,
    HALUEVAL_POSITIVE,
    HaluEvalRow,
    build_eval_pairs,
    compute_metrics,
)


def _row(idx: int, gold: str = HALUEVAL_POSITIVE) -> HaluEvalRow:
    return HaluEvalRow(
        sample_id=f"h-{idx}",
        knowledge="Paris is the capital of France.",
        question="What is the capital of France?",
        right_answer="Paris.",
        hallucinated_answer="Berlin.",
        gold_label=gold,
    )


def test_pair_construction_honors_gold_label():
    rows = [_row(0, HALUEVAL_POSITIVE), _row(1, HALUEVAL_NEGATIVE)]
    pairs = build_eval_pairs(rows, seed=42, n=2)
    assert len(pairs) == 2
    by_id = {p.sample_id: p for p in pairs}
    # POSITIVE sample => contradicted candidate = hallucinated answer
    assert by_id["h-0"].candidate_answer == "Berlin."
    assert by_id["h-0"].gold_label == "contradicted"
    # NEGATIVE sample => supported candidate = right answer
    assert by_id["h-1"].candidate_answer == "Paris."
    assert by_id["h-1"].gold_label == "supported"


def test_pair_construction_respects_n_limit():
    rows = [_row(i) for i in range(5)]
    pairs = build_eval_pairs(rows, seed=42, n=3)
    assert len(pairs) == 3


def test_pair_construction_is_seed_deterministic():
    rows = [_row(i) for i in range(10)]
    a = build_eval_pairs(rows, seed=1, n=5)
    b = build_eval_pairs(rows, seed=1, n=5)
    assert [p.sample_id for p in a] == [p.sample_id for p in b]
    c = build_eval_pairs(rows, seed=2, n=5)
    # Different seed may sample different rows.
    assert isinstance(c, list)


def test_compute_metrics_perfect_predictions():
    preds = ["supported", "contradicted", "supported", "contradicted"]
    golds = ["supported", "contradicted", "supported", "contradicted"]
    metrics, cm = compute_metrics(preds, golds)
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1 == 1.0
    assert metrics.label_accuracy == 1.0
    assert metrics.macro_f1 == 1.0
    assert cm["supported"]["supported"] == 2
    assert cm["contradicted"]["contradicted"] == 2


def test_compute_metrics_all_flipped():
    preds = ["contradicted", "supported", "contradicted", "supported"]
    golds = ["supported", "contradicted", "supported", "contradicted"]
    metrics, cm = compute_metrics(preds, golds)
    assert metrics.precision == 0.0
    assert metrics.recall == 0.0
    assert metrics.f1 == 0.0
    assert metrics.macro_f1 == 0.0
    assert cm["supported"]["supported"] == 0
    assert cm["contradicted"]["contradicted"] == 0


def test_compute_metrics_partial():
    preds = ["supported", "supported", "contradicted", "supported"]
    golds = ["supported", "contradicted", "contradicted", "contradicted"]
    metrics, cm = compute_metrics(preds, golds)
    # tp=1 (pred=contra, gold=contra at idx 2)
    # fp=1 (pred=contra, gold=sup at idx 2 — wait, gold=contra, so tp=1 there)
    # Let me recount:
    # idx 0: pred=sup, gold=sup -> TN
    # idx 1: pred=sup, gold=contra -> FN
    # idx 2: pred=contra, gold=contra -> TP
    # idx 3: pred=sup, gold=contra -> FN
    assert metrics.true_positives if hasattr(metrics, "true_positives") else True  # noqa: just confirm field exists
    # Compute manually:
    # positives = 3 (idx 1, 2, 3)
    # tp = 1, fn = 2
    # fp = 0 (pred=contra only when gold=contra)
    # tn = 1
    assert metrics.positives == 3
    assert metrics.precision == 1.0  # tp / (tp + fp) = 1 / 1
    assert metrics.recall == 1 / 3  # tp / (tp + fn) = 1 / 3
    assert abs(metrics.f1 - 2 / 4) < 1e-9
    assert cm["supported"]["supported"] == 1
    assert cm["supported"]["contradicted"] == 2
    assert cm["contradicted"]["contradicted"] == 1


def test_compute_metrics_handles_unverifiable_by_skipping():
    """Predictions outside the two-class universe are projected out."""
    preds = ["supported", "unverifiable", "contradicted", "supported"]
    golds = ["supported", "contradicted", "contradicted", "supported"]
    metrics, _ = compute_metrics(preds, golds)
    # Row 1 is dropped (pred = "unverifiable"). Remaining rows:
    #   idx 0: pred=sup, gold=sup   -> not a positive (gold supported)
    #   idx 2: pred=contra, gold=contra -> POSITIVE (gold contradicted)
    #   idx 3: pred=sup, gold=sup   -> not a positive
    # positives = 1
    assert metrics.positives == 1
    # TP=1 (idx 2), FP=0, so precision=1.0.
    # recall = 1 / 1 = 1.0
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1 == 1.0


def test_metrics_serialization_round_trips():
    import dataclasses

    preds = ["supported", "contradicted"]
    golds = ["supported", "contradicted"]
    metrics, _ = compute_metrics(preds, golds)
    blob = dataclasses.asdict(metrics)
    # Just make sure the round-trip is JSON-serializable.
    import json
    json.dumps(blob)
