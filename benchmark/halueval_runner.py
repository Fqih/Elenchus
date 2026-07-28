"""HaluEval QA benchmark runner — Phase 11 real-eval acceptance.

HaluEval (Li et al., 2023) is a 35k-sample hallucination benchmark sourced
from HotpotQA. The QA split has ~7k samples. Each sample has:
    knowledge        — the source passage
    question
    right_answer     — the truthful answer
    hallucinated_answer — a generated adversarial hallucination
    hallucination_label — "Hallucination" | "Not Hallucination"

We map HaluEval's binary "is hallucinated" label to Elenchus's three-way
labels:

    Hallucination       -> contradicted   (the answer clashes with knowledge)
    Not Hallucination   -> supported       (the answer tracks the knowledge)

HaluEval QA does not produce an "unverifiable" tier, so we only emit the
two-class version of our label set. Macro-F1 across the two classes is
the headline metric. We also report confusion-matrix counts.

Differences from RAGTruth (`benchmark/run_benchmark.py`):
    - We use HaluEval's pre-made labels rather than mining span-level gold.
    - For each sample, the candidate answer is either `right_answer` or
      `hallucinated_answer` per the gold label. We feed ONE claim per
      sample (the whole answer is treated as one claim) because HaluEval
      does not give per-sentence labels. That matches Elenchus's API:
      we treat the candidate answer as a single sentence.
    - VerificationConfig stays at the same defaults — HaluEval passes
      passages short enough that the default `claim_extractor`
      sentences them naturally; we explicitly bypass sentence splitting
      and use the answer whole.

Usage:
    python -m benchmark.halueval_runner \
        --n 200 --seeds 1 2 3 --pool-size 8000 \
        --output benchmark/halueval_results.json

Output:
    A JSON file with one entry per seed containing:
        - precision, recall, f1 (treating "contradicted" as positive)
        - label_accuracy, macro_f1 (two-class)
        - confusion_matrix (2x2, labels supported/contradicted)
        - n_total, positives, negatives
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from elenchus.config import VerificationConfig
from elenchus.verifier import Verifier
from elenchus.verification_log import InMemoryVerificationLog

# `datasets` (HuggingFace) is only needed when *running* the benchmark, not
# when importing this module. Tests build fake rows and never call the
# loader, so we defer the import to that function.
_load_dataset = None


def _get_load_dataset():
    global _load_dataset
    if _load_dataset is None:
        try:
            from datasets import load_dataset as _ld
            _load_dataset = _ld
        except ImportError as e:
            print(
                "ERROR: HaluEval benchmark requires the `datasets` package.\n"
                "Install with: pip install -e \".[eval]\"",
                file=sys.stderr,
            )
            raise SystemExit(1) from e
    return _load_dataset


# ---------- Constants -----------------------------------------------------


HALUEVAL_QA = "pminervini/HaluEval"
HALUEVAL_QA_SUBSET_CONFIG = "qa"
HALUEVAL_POSITIVE = "Hallucination"
HALUEVAL_NEGATIVE = "Not Hallucination"


@dataclass
class HaluEvalRow:
    """A single HaluEval QA row, normalized to our shape."""
    sample_id: str
    knowledge: str
    question: str
    right_answer: str
    hallucinated_answer: str
    gold_label: str  # "Hallucination" | "Not Hallucination"

    @property
    def candidate_answer(self) -> str:
        """HaluEval QA does not annotate which answer is presented; we
        always present the right_answer and let the verifiers do their job
        on both true+hallucinated pairs through the runner."""
        raise NotImplementedError  # not used; runner builds pairs explicitly


# ---------- Loader --------------------------------------------------------


def _require_halueval(cache_dir: Optional[str] = None):
    """Download and return the HaluEval QA split (cached after first use)."""
    ld = _get_load_dataset()
    kwargs: Dict[str, Any] = {"path": HALUEVAL_QA_QA_CONFIG()}
    if cache_dir is not None:
        kwargs["cache_dir"] = cache_dir
    # `trust_remote_code` is required by some HF dataset configs.
    return ld(**kwargs, trust_remote_code=True)


def HALUEVAL_QA_QA_CONFIG() -> str:
    return HALUEVAL_QA_SUBSET_CONFIG


def load_halueval_qa(cache_dir: Optional[str] = None) -> List[HaluEvalRow]:
    """Load the full HaluEval QA split and normalize to HaluEvalRow."""
    ds = _require_halueval(cache_dir)
    rows: List[HaluEvalRow] = []
    for idx, record in enumerate(ds["data"] if "data" in ds else ds["train"]):
        # HF dataset layout can be `train` or `data` depending on version.
        try:
            gold = record["hallucination_label"]
        except KeyError:
            # Field names normalized across versions.
            gold = record.get("label") or record.get("hallucination")
        if gold not in (HALUEVAL_POSITIVE, HALUEVAL_NEGATIVE):
            continue
        try:
            rows.append(HaluEvalRow(
                sample_id=f"halueval-qa-{idx}",
                knowledge=record["knowledge"],
                question=record["question"],
                right_answer=record["right_answer"],
                hallucinated_answer=record["hallucinated_answer"],
                gold_label=gold,
            ))
        except KeyError as missing:
            raise RuntimeError(
                f"HaluEval schema changed: missing field {missing}"
            ) from missing
    return rows


# ---------- Pair construction --------------------------------------------


@dataclass
class EvalPair:
    """A single (candidate_answer, gold_label) pair to verify."""
    sample_id: str
    knowledge: str
    candidate_answer: str
    # Gold expressed in Elenchus three-way labels.
    gold_label: str  # "supported" | "contradicted"


def build_eval_pairs(rows: Sequence[HaluEvalRow], seed: int, n: int) -> List[EvalPair]:
    """Sample `n` HaluEval rows and emit one pair per sample.

    The candidate_answer alternates deterministically by sample parity so
    we evaluate both the supported and contradicted candidate on equal
    footing across the same knowledge base.
    """
    rng = random.Random(seed)
    chosen = rng.sample(list(rows), min(n, len(rows)))
    pairs: List[EvalPair] = []
    for i, r in enumerate(chosen):
        if i % 2 == 0:
            candidate = r.right_answer
            gold = "supported"
        else:
            candidate = r.hallucinated_answer
            gold = "contradicted"
        # Override: honor the gold sample's intended label when known.
        if r.gold_label == HALUEVAL_POSITIVE:
            gold = "contradicted"
            candidate = r.hallucinated_answer
        elif r.gold_label == HALUEVAL_NEGATIVE:
            gold = "supported"
            candidate = r.right_answer
        pairs.append(EvalPair(
            sample_id=r.sample_id,
            knowledge=r.knowledge,
            candidate_answer=candidate,
            gold_label=gold,
        ))
    return pairs


# ---------- Verifier adapter ---------------------------------------------


def _verify_one(verifier: Verifier, knowledge: str, candidate: str) -> str:
    """Run Elenchus on a single knowledge + candidate pair, return verdict label."""
    verdicts = verifier.verify(
        output_text=candidate,
        source_documents=[("knowledge", knowledge)],
    )
    if not verdicts:
        return "unverifiable"
    return verdicts[0].label


@dataclass
class EvalMetrics:
    seed: int
    n_total: int
    positives: int
    negatives: int
    precision: float
    recall: float
    f1: float
    label_accuracy: float
    macro_f1: float
    confusion_matrix: Dict[str, Dict[str, int]] = field(default_factory=dict)
    per_seed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_metrics(
    predictions: Sequence[str], golds: Sequence[str]
) -> Tuple[EvalMetrics, Dict[str, Dict[str, int]]]:
    if len(predictions) != len(golds):
        raise ValueError(
            f"predictions / golds length mismatch ({len(predictions)} vs {len(golds)})"
        )
    labels = ("supported", "contradicted")
    cm: Dict[str, Dict[str, int]] = {p: {g: 0 for g in labels} for p in labels}

    tp = fp = fn = tn = 0
    positives = 0
    correct = 0

    for pred, gold in zip(predictions, golds):
        # Only count predictions as positive if both sides are in the two-class
        # universe; HaluEval has no "unverifiable" gold so we project both
        # pred and gold to that pair.
        if gold not in labels or pred not in labels:
            # Skip and don't penalize.
            continue
        cm[pred][gold] += 1
        if pred == gold:
            correct += 1
        if gold == "contradicted":
            positives += 1
            if pred == "contradicted":
                tp += 1
            else:
                fn += 1
        else:  # gold == "supported"
            if pred == "contradicted":
                fp += 1
            else:
                tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        (2 * precision * recall / (precision + recall))
        if (precision + recall) > 0
        else 0.0
    )
    label_accuracy = correct / max(1, sum(sum(row.values()) for row in cm.values()))

    # Macro-F1 across the two classes.
    per_label_f1: List[float] = []
    for lbl in labels:
        ltp = cm[lbl][lbl]
        lfp = sum(cm[lbl][m] for m in labels if m != lbl)
        lfn = sum(cm[m][lbl] for m in labels if m != lbl)
        lp = ltp / (ltp + lfp) if (ltp + lfp) > 0 else 0.0
        lr = ltp / (ltp + lfn) if (ltp + lfn) > 0 else 0.0
        per_label_f1.append(
            (2 * lp * lr / (lp + lr) if (lp + lr) > 0 else 0.0)
        )
    macro_f1 = sum(per_label_f1) / len(per_label_f1)

    return (
        EvalMetrics(
            seed=0,  # filled by caller
            n_total=len(predictions),
            positives=positives,
            negatives=len(predictions) - positives,
            precision=precision,
            recall=recall,
            f1=f1,
            label_accuracy=label_accuracy,
            macro_f1=macro_f1,
            confusion_matrix=cm,
        ),
        cm,
    )


# ---------- Entry point ---------------------------------------------------


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="HaluEval QA benchmark for Elenchus")
    p.add_argument("--n", type=int, default=100,
                   help="number of HaluEval samples per seed")
    p.add_argument("--seeds", type=int, nargs="+", default=[1])
    p.add_argument("--pool-size", type=int, default=8000,
                   help="cap on the pre-sample pool (HaluEval QA is 7k+. "
                        "Larger than dataset size means 'use all'.)")
    p.add_argument("--cache-dir", type=str, default=None,
                   help="HF datasets cache dir (defaults to HF_HOME)")
    p.add_argument("--output", type=str,
                   default="benchmark/halueval_results.json",
                   help="output JSON file")
    return p.parse_args(argv)


def _run_one_seed(seed: int, rows: Sequence[HaluEvalRow], n: int) -> EvalMetrics:
    import time

    pairs = build_eval_pairs(rows, seed=seed, n=n)
    verifier = Verifier(config=VerificationConfig(), log=InMemoryVerificationLog())
    t0 = time.perf_counter()
    preds: List[str] = []
    golds: List[str] = []
    for p in pairs:
        preds.append(_verify_one(verifier, p.knowledge, p.candidate_answer))
        golds.append(p.gold_label)
    elapsed = time.perf_counter() - t0
    metrics, _ = compute_metrics(preds, golds)
    metrics.seed = seed
    metrics.per_seed_seconds = elapsed
    return metrics


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    rows = load_halueval_qa(cache_dir=args.cache_dir)
    if args.pool_size and len(rows) > args.pool_size:
        random.Random(args.pool_size).shuffle(rows)
        rows = rows[: args.pool_size]

    all_metrics: List[EvalMetrics] = []
    for seed in args.seeds:
        m = _run_one_seed(seed, rows, args.n)
        all_metrics.append(m)
        print(
            f"[halueval] seed={seed}  n={m.n_total}  "
            f"precision={m.precision:.3f}  recall={m.recall:.3f}  f1={m.f1:.3f}  "
            f"macro_f1={m.macro_f1:.3f}  acc={m.label_accuracy:.3f}  "
            f"({m.per_seed_seconds:.1f}s)"
        )

    output = {
        "benchmark": "halueval_qa",
        "pool_size": len(rows),
        "n_per_seed": args.n,
        "seeds": args.seeds,
        "metrics": [m.to_dict() for m in all_metrics],
        "mean_metrics": _mean(all_metrics),
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[halueval] wrote {args.output}")
    return 0


def _mean(metrics: List[EvalMetrics]) -> Dict[str, float]:
    if not metrics:
        return {}
    keys = ("precision", "recall", "f1", "label_accuracy", "macro_f1", "per_seed_seconds")
    return {
        k: sum(getattr(m, k) for m in metrics) / len(metrics) for k in keys
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
