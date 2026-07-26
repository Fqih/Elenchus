"""RAGTruth benchmark runner — Phase 3 acceptance.

Three approaches are compared head-to-head on a sampled slice of RAGTruth:

    1. Cosine-similarity baseline — sentence-transformers embedding cosine
       between claim and source passages, thresholded to decide supported vs
       contradicted. This is the simplest faithful-unfaithful baseline.
    2. NLI-only baseline — the same local NLI model Elenchus uses, but with
       no confidence-gap escalation. Tests whether the NLI model alone is
       enough without Tier 2.
    3. Elenchus tiered — NLI Tier 1 with a deterministic, intentionally
       conservative keyword judge for Tier 2 (so we don't need an LLM
       provider just to benchmark). When Tier 1 is confident the judge is
       skipped; when it's ambiguous, the judge decides.

Outputs JSON metrics + per-seed breakdown, plus a printed summary table.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Collection,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)

from benchmark.prepare_dataset import RagtruthRecord, load_prepared
from elenchus.config import VerificationConfig

if TYPE_CHECKING:
    from elenchus.types import Verdict


_DEFAULT_VERIFICATION_CONFIG = VerificationConfig()
_NLI_ONLY_THRESHOLD = 0.0
_DEFAULT_COSINE_THRESHOLD = 0.5


# ---------- Data shapes ------------------------------------------------------


@dataclass
class BenchmarkRow:
    response_id: str
    source_id: str
    claim_text: str
    source_text: str
    gold_label: str  # "supported", "contradicted", or "unverifiable"

    @classmethod
    def from_ragtruth(cls, r: RagtruthRecord) -> "BenchmarkRow":
        return cls(
            response_id=r.response_id,
            source_id=r.source_id,
            claim_text=r.claim_text,
            source_text=r.source_text,
            gold_label=r.gold_label,
        )


@dataclass
class BenchmarkRun:
    seed: int
    n_total: int
    precision: float
    recall: float
    f1: float
    label_accuracy: float
    macro_f1: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    positive_total: int
    supported_predicted_hallucinated: int
    escalation_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Stable metric keys so RESULTS.md tooling can rely on them.
METRIC_KEYS = (
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
)


# ---------- Metric math ------------------------------------------------------


def compute_metrics(
    predictions: Sequence[str],
    golds: Sequence[str],
    positive_label: str = "contradicted",
    positive_labels: Optional[Collection[str]] = None,
    escalation_count: int = 0,
) -> Dict[str, Any]:
    """Detection PR/F1 plus exact three-way label accuracy and macro-F1.

    ``positive_labels`` allows RAGTruth evaluation to treat both contradicted
    and unverifiable as hallucinations while still preserving their exact
    three-way labels for accuracy and macro-F1.
    """
    if len(predictions) != len(golds):
        raise ValueError(
            "predictions and golds must have identical lengths "
            f"({len(predictions)} != {len(golds)})"
        )
    positive_set = set(positive_labels or {positive_label})
    tp = fp = tn = fn = 0
    positive_total = 0
    supported_predicted_hallucinated = 0
    for pred, gold in zip(predictions, golds):
        gold_positive = gold in positive_set
        pred_positive = pred in positive_set
        if gold_positive:
            positive_total += 1
            if pred_positive:
                tp += 1
            else:
                fn += 1
        else:
            if pred_positive:
                fp += 1
                supported_predicted_hallucinated += 1
            else:
                tn += 1
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        (2 * precision * recall / (precision + recall))
        if (precision + recall) > 0
        else 0.0
    )
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "label_accuracy": _label_accuracy(predictions, golds),
        "macro_f1": _macro_f1(predictions, golds),
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "positive_total": positive_total,
        "supported_predicted_hallucinated": supported_predicted_hallucinated,
        "escalation_count": escalation_count,
        "n_total": len(predictions),
    }


def _label_accuracy(predictions: Sequence[str], golds: Sequence[str]) -> float:
    if not predictions:
        return 0.0
    return sum(pred == gold for pred, gold in zip(predictions, golds)) / len(
        predictions
    )


def _macro_f1(predictions: Sequence[str], golds: Sequence[str]) -> float:
    labels = sorted(set(predictions) | set(golds))
    if not labels:
        return 0.0
    per_label: List[float] = []
    for label in labels:
        tp = sum(
            pred == label and gold == label for pred, gold in zip(predictions, golds)
        )
        fp = sum(
            pred == label and gold != label for pred, gold in zip(predictions, golds)
        )
        fn = sum(
            pred != label and gold == label for pred, gold in zip(predictions, golds)
        )
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        per_label.append(
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
    return sum(per_label) / len(per_label)


def metrics_to_run(metrics: Dict[str, Any], seed: int) -> BenchmarkRun:
    return BenchmarkRun(
        seed=seed,
        n_total=int(metrics["n_total"]),
        precision=float(metrics["precision"]),
        recall=float(metrics["recall"]),
        f1=float(metrics["f1"]),
        label_accuracy=float(metrics["label_accuracy"]),
        macro_f1=float(metrics["macro_f1"]),
        true_positives=int(metrics["true_positives"]),
        false_positives=int(metrics["false_positives"]),
        true_negatives=int(metrics["true_negatives"]),
        false_negatives=int(metrics["false_negatives"]),
        positive_total=int(metrics["positive_total"]),
        supported_predicted_hallucinated=int(
            metrics["supported_predicted_hallucinated"]
        ),
        escalation_count=int(metrics["escalation_count"]),
    )


# ---------- Cosine baseline --------------------------------------------------


def cosine_predict(
    row: BenchmarkRow,
    embedder,
    threshold: float = _DEFAULT_COSINE_THRESHOLD,
) -> str:
    """Encode claim + source, compute max cosine sim across sentence chunks of
    the source. If max sim ≥ threshold, predict supported, else contradicted.
    """
    claim_vec = embedder.encode([row.claim_text])[0]
    source_chunks = _split_into_sentences(row.source_text) or [row.source_text]
    src_vecs = embedder.encode(source_chunks)
    best = _max_cosine(claim_vec, src_vecs)
    return "supported" if best >= threshold else "contradicted"


def _split_into_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _max_cosine(claim_vec, src_vecs) -> float:
    import numpy as np

    c = np.asarray(claim_vec, dtype=np.float32).reshape(-1)
    s = np.asarray(src_vecs, dtype=np.float32)
    if s.ndim == 1:
        s = s.reshape(1, -1)
    cn = c / (np.linalg.norm(c) + 1e-12)
    sn = s / (np.linalg.norm(s, axis=1, keepdims=True) + 1e-12)
    sims = sn @ cn
    return float(sims.max())


# ---------- NLI-only baseline -----------------------------------------------


def nli_only_predict(row: BenchmarkRow, nli) -> str:
    """Run Elenchus's production ``Verifier`` with escalation disabled."""
    # Both routing thresholds are zero so this baseline always accepts Tier
    # 1's own verdict and never enters the optional judge path.
    cfg = VerificationConfig(
        confidence_gap_threshold=_NLI_ONLY_THRESHOLD,
        nli_decision_threshold=_NLI_ONLY_THRESHOLD,
    )
    verdict = _verify_row(row=row, nli=nli, config=cfg)
    return verdict.label


# ---------- Tiered predictor ------------------------------------------------


def tiered_predict(
    row: BenchmarkRow,
    nli,
    judge: Optional[Callable],
    gap_threshold: float = _DEFAULT_VERIFICATION_CONFIG.confidence_gap_threshold,
) -> Tuple[str, bool]:
    """Tier 1 NLI + optional Tier 2 escalation.

    Returns (predicted_label, escalated_bool). When Tier 1 is confident
    (gap ≥ threshold), the judge is not invoked. When Tier 1 is ambiguous
    (gap < threshold), the judge decides — or, if no judge is configured,
    we return `unverifiable` per Rule 3.
    """
    cfg = VerificationConfig(
        confidence_gap_threshold=gap_threshold,
        llm_judge=judge,
    )
    verdict = _verify_row(row=row, nli=nli, config=cfg)
    return verdict.label, verdict.tier == "llm_judge"


def _verify_row(row: BenchmarkRow, nli, config):
    """Evaluate one benchmark row through the public production pipeline."""
    from elenchus.verification_log import InMemoryVerificationLog
    from elenchus.verifier import Verifier

    log = InMemoryVerificationLog()
    verifier = Verifier(config=config, log=log, nli=nli)
    verdict = verifier.verify_claim(
        claim=_claim_for_row(row),
        source_documents=[(row.source_id, row.source_text)],
    )
    if len(log) != 1:
        raise RuntimeError(
            "benchmark verification did not produce exactly one log entry"
        )
    return verdict


def _claim_for_row(row: BenchmarkRow):
    from elenchus.types import Claim

    return Claim(
        id=f"{row.response_id}::{row.claim_text[:32]}",
        text=row.claim_text,
        span=(0, len(row.claim_text)),
    )


# ---------- Tier-2 judge stand-in (deterministic) --------------------------


_NUM_RE = re.compile(r"\b\d{2,4}\b")
_KEYWORD_SUPPORT_RELEVANCE_THRESHOLD = 0.85
_KEYWORD_CONTRADICTION_CONFIDENCE = 0.7
_KEYWORD_SUPPORT_CONFIDENCE = 0.6
_KEYWORD_ABSTENTION_CONFIDENCE = 0.5


def keyword_judge(claim, evidence) -> "Verdict":
    """Deterministic Tier-2 stand-in used by the benchmark.

    Looks for numerical disagreement between claim and source (the most
    common failure mode in RAGTruth responses — years, counts, dates).
    If a number in the claim isn't in the source, the judge calls it
    contradicted. It calls a claim supported only when a number is accounted
    for or lexical coverage is very high; otherwise it abstains as
    unverifiable. Returns a real `Verdict` so the Elenchus log path is
    exercised the same way it would be with an LLM judge.

    Signature matches `elenchus.llm_judge.invoke_judge`'s contract:
    takes a Claim and a list of Evidence, returns a Verdict.
    """
    from datetime import datetime, timezone
    from elenchus.types import Verdict

    claim_text = claim.text
    source_text = " ".join(item.text for item in evidence)

    claim_nums = set(_NUM_RE.findall(claim_text))
    source_nums = set(_NUM_RE.findall(source_text))
    extras = claim_nums - source_nums
    from elenchus.evidence_retriever import lexical_relevance

    best_relevance = max(
        (lexical_relevance(claim_text, item.text) for item in evidence),
        default=0.0,
    )
    if extras:
        label = "contradicted"
        confidence = _KEYWORD_CONTRADICTION_CONFIDENCE
    elif claim_nums or best_relevance >= _KEYWORD_SUPPORT_RELEVANCE_THRESHOLD:
        label = "supported"
        confidence = _KEYWORD_SUPPORT_CONFIDENCE
    else:
        # This deterministic stand-in has no semantic basis for deciding a
        # non-numeric ambiguous case. Abstain instead of fabricating support.
        label = "unverifiable"
        confidence = _KEYWORD_ABSTENTION_CONFIDENCE
    return Verdict(
        claim=claim,
        label=label,  # type: ignore[arg-type]
        confidence=confidence,
        tier="llm_judge",
        evidence=evidence[0] if evidence and label != "unverifiable" else None,
        checked_at=datetime.now(timezone.utc),
    )


# ---------- Run orchestration -----------------------------------------------


_DEFAULT_N = 200  # per-seed subset size


def _subset(
    rows: List[BenchmarkRow],
    n: int,
    seed: int,
    contradicted_fraction: Optional[float] = None,
) -> List[BenchmarkRow]:
    """Take a stratified random subset of size `n`.

    `contradicted_fraction` lets us balance the subset. If `None`, we use
    the dataset's natural class balance.
    """
    rng = random.Random(seed)
    pool = list(rows)
    rng.shuffle(pool)
    if contradicted_fraction is None:
        return pool[:n]
    # Stratified: take up to n*frac from contradicted, the rest from supported.
    contrad = [r for r in pool if r.gold_label == "contradicted"]
    supp = [r for r in pool if r.gold_label == "supported"]
    rng.shuffle(contrad)
    rng.shuffle(supp)
    n_contra = int(round(n * contradicted_fraction))
    n_supp = n - n_contra
    out = contrad[:n_contra] + supp[:n_supp]
    rng.shuffle(out)
    return out


def run_seed(
    rows: List[BenchmarkRow],
    seed: int,
    *,
    embedder,
    nli,
    judge,
    n: int = _DEFAULT_N,
    gap_threshold: float = _DEFAULT_VERIFICATION_CONFIG.confidence_gap_threshold,
    cosine_threshold: float = _DEFAULT_COSINE_THRESHOLD,
) -> Dict[str, BenchmarkRun]:
    """Run all three approaches on the same subset of `rows` and return
    a dict {approach_name: BenchmarkRun}.

    The subset is taken with the same seed across approaches, so each
    approach is evaluated on identical (claim, source, gold) triples —
    making the comparison apples-to-apples.
    """
    sub = _subset(rows, n=min(len(rows), n), seed=seed)
    if not sub:
        raise ValueError("empty subset")

    cos_preds = [
        cosine_predict(r, embedder=embedder, threshold=cosine_threshold) for r in sub
    ]
    nli_preds = [nli_only_predict(r, nli=nli) for r in sub]

    tier_preds: List[str] = []
    escalations = 0
    for r in sub:
        pred, escalated = tiered_predict(
            r, nli=nli, judge=judge, gap_threshold=gap_threshold
        )
        tier_preds.append(pred)
        if escalated:
            escalations += 1

    golds = [r.gold_label for r in sub]
    hallucination_labels = {"contradicted", "unverifiable"}
    cos_m = compute_metrics(cos_preds, golds, positive_labels=hallucination_labels)
    nli_m = compute_metrics(nli_preds, golds, positive_labels=hallucination_labels)
    tier_m = compute_metrics(
        tier_preds,
        golds,
        positive_labels=hallucination_labels,
        escalation_count=escalations,
    )
    return {
        "cosine": metrics_to_run(cos_m, seed),
        "nli_only": metrics_to_run(nli_m, seed),
        "tiered": metrics_to_run(tier_m, seed),
    }


# ---------- CLI entry point --------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    """Run the benchmark on a subsample of RAGTruth. Writes JSON results."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).parent / "data" / "dataset.jsonl"),
        help="Path to the prepared RAGTruth dataset.jsonl",
    )
    parser.add_argument(
        "--pool-size",
        type=int,
        default=2000,
        help="Max rows loaded into memory (stratified subset for the run)",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=_DEFAULT_N,
        help="Per-seed subset size",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=[1, 2, 3],
        help="Random seeds for stability check",
    )
    parser.add_argument(
        "--cosine-model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Sentence embedder for the cosine baseline",
    )
    parser.add_argument(
        "--nli-model",
        default=_DEFAULT_VERIFICATION_CONFIG.nli_model_name,
        help="NLI model for NLI-only and tiered approaches",
    )
    parser.add_argument(
        "--cosine-threshold",
        type=float,
        default=_DEFAULT_COSINE_THRESHOLD,
        help="Decision threshold for the cosine baseline",
    )
    parser.add_argument(
        "--gap-threshold",
        type=float,
        default=_DEFAULT_VERIFICATION_CONFIG.confidence_gap_threshold,
        help="Tier-1 confidence-gap threshold for the tiered approach",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent / "data" / "benchmark_results.json"),
        help="Where to write JSON results",
    )
    args = parser.parse_args(argv)

    print(f"Loading {args.dataset} (capped at {args.pool_size} rows)…", file=sys.stderr)
    raw = load_prepared(args.dataset, limit=args.pool_size)
    rows = [BenchmarkRow.from_ragtruth(r) for r in raw]
    label_counts = {
        label: sum(1 for row in rows if row.gold_label == label)
        for label in ("supported", "contradicted", "unverifiable")
    }
    print(
        f"  loaded {len(rows)} sentences "
        f"({label_counts['supported']} supported, "
        f"{label_counts['contradicted']} contradicted, "
        f"{label_counts['unverifiable']} unverifiable)",
        file=sys.stderr,
    )

    # Lazy imports keep startup fast for `--help`.
    from sentence_transformers import SentenceTransformer

    print(f"Loading cosine model: {args.cosine_model}", file=sys.stderr)
    embedder = SentenceTransformer(args.cosine_model)

    print(f"Loading NLI model: {args.nli_model}", file=sys.stderr)
    from elenchus.nli_verifier import NliVerifier

    nli = NliVerifier(VerificationConfig(nli_model_name=args.nli_model))

    all_runs: Dict[str, List[BenchmarkRun]] = {
        "cosine": [],
        "nli_only": [],
        "tiered": [],
    }
    for seed in args.seeds:
        print(f"\n--- seed={seed} ---", file=sys.stderr)
        runs = run_seed(
            rows=rows,
            seed=seed,
            embedder=embedder,
            nli=nli,
            judge=keyword_judge,
            n=args.n,
            gap_threshold=args.gap_threshold,
            cosine_threshold=args.cosine_threshold,
        )
        for name, run in runs.items():
            all_runs[name].append(run)
            print(
                f"  {name:<10}  P={run.precision:.3f}  R={run.recall:.3f}  "
                f"F1={run.f1:.3f}  macroF1={run.macro_f1:.3f}  "
                f"acc={run.label_accuracy:.3f}  "
                f"esc={run.escalation_count}/{run.n_total}",
                file=sys.stderr,
            )

    summary = _summarize(all_runs)
    summary["run_config"] = {
        "dataset": args.dataset,
        "pool_size": args.pool_size,
        "n_per_seed": args.n,
        "seeds": args.seeds,
        "cosine_model": args.cosine_model,
        "nli_model": args.nli_model,
        "cosine_threshold": args.cosine_threshold,
        "nli_only_confidence_gap_threshold": _NLI_ONLY_THRESHOLD,
        "nli_only_decision_threshold": _NLI_ONLY_THRESHOLD,
        "nli_decision_threshold": (_DEFAULT_VERIFICATION_CONFIG.nli_decision_threshold),
        "confidence_gap_threshold": args.gap_threshold,
        "max_evidence_passages_per_claim": (
            _DEFAULT_VERIFICATION_CONFIG.max_evidence_passages_per_claim
        ),
        "max_evidence_window_chunks": (
            _DEFAULT_VERIFICATION_CONFIG.max_evidence_window_chunks
        ),
        "hallucination_detection_labels": ["contradicted", "unverifiable"],
        "semantic_label_mapping": {
            "Evident Conflict": "contradicted",
            "Evident Baseless Info": "unverifiable",
            "Subtle Baseless Info": "unverifiable",
        },
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}", file=sys.stderr)
    return 0


# Tiny helper to keep the formatting one-liner above readable.
def _summarize(all_runs: Dict[str, List[BenchmarkRun]]) -> Dict[str, Any]:
    import statistics

    out: Dict[str, Any] = {"approaches": {}}
    for name, runs in all_runs.items():
        f1s = [r.f1 for r in runs]
        ps = [r.precision for r in runs]
        rs = [r.recall for r in runs]
        accuracies = [r.label_accuracy for r in runs]
        macro_f1s = [r.macro_f1 for r in runs]
        escalation_rates = [
            r.escalation_count / r.n_total if r.n_total else 0.0 for r in runs
        ]
        out["approaches"][name] = {
            "seeds": [r.to_dict() for r in runs],
            "f1_mean": statistics.fmean(f1s) if f1s else 0.0,
            "f1_stdev": statistics.pstdev(f1s) if len(f1s) > 1 else 0.0,
            "precision_mean": statistics.fmean(ps) if ps else 0.0,
            "precision_stdev": (statistics.pstdev(ps) if len(ps) > 1 else 0.0),
            "recall_mean": statistics.fmean(rs) if rs else 0.0,
            "recall_stdev": (statistics.pstdev(rs) if len(rs) > 1 else 0.0),
            "label_accuracy_mean": (
                statistics.fmean(accuracies) if accuracies else 0.0
            ),
            "label_accuracy_stdev": (
                statistics.pstdev(accuracies) if len(accuracies) > 1 else 0.0
            ),
            "macro_f1_mean": statistics.fmean(macro_f1s) if macro_f1s else 0.0,
            "macro_f1_stdev": (
                statistics.pstdev(macro_f1s) if len(macro_f1s) > 1 else 0.0
            ),
            "escalation_rate_mean": (
                statistics.fmean(escalation_rates) if escalation_rates else 0.0
            ),
            "escalation_rate_stdev": (
                statistics.pstdev(escalation_rates)
                if len(escalation_rates) > 1
                else 0.0
            ),
        }
    return out


if __name__ == "__main__":
    raise SystemExit(main())
