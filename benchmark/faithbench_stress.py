"""Disputed-case escalation stress proxy — Phase 3, Rule 8.

FaithBench is annotated cases where humans DISAGREE about whether a
claim is hallucinated. No FaithBench artifact is checked into this
project, so this development run uses RAGTruth's `implicit_true=true`
spans — cases the annotators marked as hallucinated even though the
underlying fact is true (i.e. not directly stated in source). These
are a proxy for "disputed / hard cases" and exercise the related
question of whether Tier-2 escalation catches claims Tier 1 would
otherwise miss or undersell.

Per Rule 8, these numbers are reported as a SEPARATE section in
RESULTS.md — never combined with the RAGTruth precision/recall numbers.

We measure two things:

    - Escalation rate: what fraction of disputed cases the confidence-gap
      threshold escalates to Tier 2.
    - Flip rate: given an escalation, how often the Tier 2 judge flips
      the Tier 1 label (the whole point of escalation).
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark.prepare_dataset import RagtruthRecord, load_prepared
from elenchus.config import VerificationConfig


_DEFAULT_VERIFICATION_CONFIG = VerificationConfig()


# ---------- Data shapes ------------------------------------------------------


@dataclass
class ImplicitTrueSlice:
    response_id: str
    source_id: str
    claim_text: str
    source_text: str
    n_implicit_true_spans: int
    label_types_in_span: List[str]


@dataclass
class StressRun:
    seed: int
    n_total: int
    n_escalated: int
    n_label_flipped: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------- Slice construction ----------------------------------------------


def build_implicit_true_slice(rows: List[RagtruthRecord]) -> List[ImplicitTrueSlice]:
    """Proxy for FaithBench's disputed-case subset.

    Uses RAGTruth's preserved `implicit_true=true` count as the disputed signal.
    """
    out: List[ImplicitTrueSlice] = []
    for r in rows:
        n = r.implicit_true_count
        if n == 0:
            continue
        out.append(
            ImplicitTrueSlice(
                response_id=r.response_id,
                source_id=r.source_id,
                claim_text=r.claim_text,
                source_text=r.source_text,
                n_implicit_true_spans=n,
                label_types_in_span=list(r.label_types_in_span),
            )
        )
    return out


# ---------- Metric math ------------------------------------------------------


def compute_stress_metrics(
    n_total: int,
    n_escalated: int,
    n_label_flipped: int,
) -> Dict[str, Any]:
    esc_rate = n_escalated / n_total if n_total > 0 else 0.0
    flip_rate = n_label_flipped / n_escalated if n_escalated > 0 else 0.0
    return {
        "n_total": n_total,
        "n_escalated": n_escalated,
        "n_label_flipped": n_label_flipped,
        "escalation_rate": esc_rate,
        "flip_rate_given_escalated": flip_rate,
    }


# ---------- Run orchestration -----------------------------------------------


def run_stress(
    slice_rows: List[ImplicitTrueSlice],
    seed: int,
    *,
    nli,
    judge,
    gap_threshold: float = _DEFAULT_VERIFICATION_CONFIG.confidence_gap_threshold,
    max_n: int = 200,
) -> StressRun:
    """Run the tiered predictor on the disputed-case slice.

    For each case we measure whether the confidence-gap escalates the
    case to Tier 2, and whether the Tier 2 judge flips the Tier 1 label.
    """
    from benchmark.run_benchmark import BenchmarkRow, tiered_predict

    rng = random.Random(seed)
    pool = list(slice_rows)
    rng.shuffle(pool)
    sample = pool[:max_n]

    n_escalated = 0
    n_flipped = 0
    for s in sample:
        row = BenchmarkRow(
            response_id=s.response_id,
            source_id=s.source_id,
            claim_text=s.claim_text,
            source_text=s.source_text,
            gold_label="unverifiable",
        )
        # Compare the actual NLI-only production path with the actual tiered
        # production path. Previously the no-judge fallback was used as the
        # Tier-1 label, which made every escalated non-unverifiable judge
        # response look like a label flip by construction.
        from benchmark.run_benchmark import nli_only_predict

        t1_pred = nli_only_predict(row, nli=nli)
        t2_pred, escalated = tiered_predict(
            row, nli=nli, judge=judge, gap_threshold=gap_threshold
        )
        if escalated:
            n_escalated += 1
            if t1_pred != t2_pred:
                n_flipped += 1

    return StressRun(
        seed=seed,
        n_total=len(sample),
        n_escalated=n_escalated,
        n_label_flipped=n_flipped,
    )


# ---------- CLI entry point -------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).parent / "data" / "dataset.jsonl"),
    )
    parser.add_argument(
        "--pool-size",
        type=int,
        default=20000,
    )
    parser.add_argument(
        "--max-n",
        type=int,
        default=200,
        help="Maximum disputed cases to evaluate per seed",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=[1, 2, 3],
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent / "data" / "stress_results.json"),
    )
    parser.add_argument(
        "--gap-threshold",
        type=float,
        default=_DEFAULT_VERIFICATION_CONFIG.confidence_gap_threshold,
    )
    args = parser.parse_args(argv)

    print(f"Loading {args.dataset}…", file=sys.stderr)
    rows = load_prepared(args.dataset, limit=args.pool_size)
    slice_rows = build_implicit_true_slice(rows)
    print(
        f"  disputed slice (implicit_true=true): {len(slice_rows)} rows",
        file=sys.stderr,
    )

    if not slice_rows:
        print("Nothing to evaluate. Exiting.", file=sys.stderr)
        return 0

    from sentence_transformers import SentenceTransformer  # noqa: F401  (kept for parity)
    from elenchus.nli_verifier import NliVerifier
    from benchmark.run_benchmark import keyword_judge

    print("Loading NLI model…", file=sys.stderr)
    nli = NliVerifier(VerificationConfig())

    runs: List[StressRun] = []
    for seed in args.seeds:
        run = run_stress(
            slice_rows=slice_rows,
            seed=seed,
            nli=nli,
            judge=keyword_judge,
            gap_threshold=args.gap_threshold,
            max_n=args.max_n,
        )
        runs.append(run)
        m = compute_stress_metrics(run.n_total, run.n_escalated, run.n_label_flipped)
        print(
            f"  seed={seed}  n={run.n_total}  escalated={run.n_escalated}  "
            f"flipped={run.n_label_flipped}  esc_rate={m['escalation_rate']:.1%}  "
            f"flip_rate={m['flip_rate_given_escalated']:.1%}",
            file=sys.stderr,
        )

    summary = {
        "n_disputed_total_in_slice": len(slice_rows),
        "approach": "tiered with keyword_judge as Tier-2 stand-in",
        "gap_threshold": args.gap_threshold,
        "runs": [r.to_dict() for r in runs],
        "metrics_per_seed": [
            compute_stress_metrics(r.n_total, r.n_escalated, r.n_label_flipped)
            for r in runs
        ],
        "mean_escalation_rate": _mean([r.n_escalated for r in runs])
        / _mean([r.n_total for r in runs])
        if runs and _mean([r.n_total for r in runs]) > 0
        else 0.0,
        "mean_flip_rate_given_escalated": _mean(
            [
                r.n_label_flipped / r.n_escalated if r.n_escalated > 0 else 0.0
                for r in runs
            ]
        ),
        "note": (
            "Development proxy using RAGTruth's explicit `implicit_true` "
            "annotations; this is not a FaithBench result. Per Rule 8 these "
            "numbers are NOT combined with the RAGTruth metrics in "
            "benchmark_results.json."
        ),
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(f"Wrote {out}", file=sys.stderr)
    return 0


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
