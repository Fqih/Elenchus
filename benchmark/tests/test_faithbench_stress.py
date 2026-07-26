"""Tests for the Phase 3 disputed-case escalation stress proxy.

FaithBench is annotated cases where humans DISAGREE about whether a claim
is hallucinated. The project has no checked-in FaithBench artifact, so these
tests exercise the RAGTruth `implicit_true=true` proxy: those are spans that
the annotators marked as hallucinations even though the underlying fact
is true (just not stated in the source). These are the closest available
proxy for "disputed / hard cases" and exercise the same property
FaithBench does — whether Tier-2 escalation catches claims Tier 1 would
otherwise miss.

We test the math: how many implicit-true spans fall into the
"escalate to Tier 2" bucket, and what fraction of those flips the
label. The numbers are reported as a SEPARATE section in RESULTS.md,
never merged with RAGTruth numbers (Rule 8).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.faithbench_stress import (
    StressRun,
    build_implicit_true_slice,
    compute_stress_metrics,
)
from benchmark.prepare_dataset import (
    RagtruthRecord,
    load_responses,
    load_source_info,
    build_dataset,
)


# ---------- Helpers ----------------------------------------------------------


def _rt(response_id, source_id, claim, source, label_types, implicit_trues):
    return RagtruthRecord(
        response_id=response_id,
        source_id=source_id,
        claim_text=claim,
        claim_span_in_response=(0, len(claim)),
        source_text=source,
        gold_label="contradicted",
        label_types_in_span=list(label_types),
        implicit_true_count=sum(bool(value) for value in implicit_trues),
    )


# ---------- build_implicit_true_slice ---------------------------------------


def test_build_implicit_true_slice_filters_to_only_implicit_true_records() -> None:
    rows = [
        _rt("a", "s1", "claim A", "src A", ["Subtle Baseless Info"], [True]),
        _rt("b", "s1", "claim B", "src B", ["Evident Conflict"], [False]),
        _rt("c", "s1", "claim C", "src C", ["Subtle Baseless Info"], [True]),
    ]
    # Add the implicit_true info via the label_types_in_span post-hoc.
    # For the test we patch the records to carry it explicitly.
    out = build_implicit_true_slice(rows)
    assert len(out) == 2
    assert {r.response_id for r in out} == {"a", "c"}


def test_build_implicit_true_slice_empty_when_no_implicit_true_records() -> None:
    rows = [
        _rt("a", "s1", "claim A", "src A", ["Evident Conflict"], [False]),
        _rt("b", "s1", "claim B", "src B", ["Evident Conflict"], [False]),
    ]
    out = build_implicit_true_slice(rows)
    assert out == []


def test_build_implicit_true_slice_carries_implicit_true_count() -> None:
    rows = [
        _rt("a", "s1", "claim A", "src A", ["Subtle Baseless Info"], [True]),
    ]
    out = build_implicit_true_slice(rows)
    assert out[0].n_implicit_true_spans == 1


# ---------- compute_stress_metrics ------------------------------------------


def test_compute_stress_metrics_ideal_escalation() -> None:
    # All cases escalated and all labels flipped to contradicted → ideal.
    metrics = compute_stress_metrics(
        n_total=10,
        n_escalated=10,
        n_label_flipped=10,
    )
    assert metrics["escalation_rate"] == 1.0
    assert metrics["flip_rate_given_escalated"] == 1.0
    assert metrics["n_total"] == 10


def test_compute_stress_metrics_no_escalation() -> None:
    metrics = compute_stress_metrics(n_total=10, n_escalated=0, n_label_flipped=0)
    assert metrics["escalation_rate"] == 0.0
    # Flip rate is undefined when nothing escalates → report 0.0, not NaN.
    assert metrics["flip_rate_given_escalated"] == 0.0


def test_compute_stress_metrics_partial() -> None:
    metrics = compute_stress_metrics(n_total=4, n_escalated=2, n_label_flipped=1)
    assert metrics["escalation_rate"] == 0.5
    assert metrics["flip_rate_given_escalated"] == 0.5


# ---------- StressRun --------------------------------------------------------


def test_stress_run_serializes_to_dict() -> None:
    run = StressRun(seed=1, n_total=10, n_escalated=5, n_label_flipped=3)
    d = run.to_dict()
    assert d["seed"] == 1
    assert d["n_escalated"] == 5
    assert d["n_label_flipped"] == 3


# ---------- End-to-end on the real JSONL -------------------------------------


@pytest.mark.skipif(
    not Path("benchmark/data/response.jsonl").exists(),
    reason="RAGTruth response.jsonl not downloaded",
)
def test_real_implicit_true_set_is_non_empty() -> None:
    """The implicit-true slice is the proxy for FaithBench's disputed cases."""
    responses = load_responses("benchmark/data/response.jsonl")
    sources = load_source_info("benchmark/data/source_info.jsonl")
    rows = build_dataset(responses=responses, sources=sources)
    slice_rows = build_implicit_true_slice(rows)
    assert len(slice_rows) > 0, "expected at least some implicit-true cases"
