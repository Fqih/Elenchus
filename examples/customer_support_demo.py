"""Flagship customer-support demo — Phase 3 acceptance.

A synthetic knowledge base with a mix of clean and deliberately-hallucinated
bot answers. Each bot answer is checked against the KB by Elenchus. The demo
prints:

    - Per-case verdicts (label, confidence, tier, evidence excerpt).
    - Aggregate detection rate: TP / (TP + FN) over the hallucinated set.
    - Aggregate false-positive rate: FP / (FP + TN) over the clean set.
    - A rendered side-by-side view of one hallucinated case and one clean
      case using the Phase 2 rendering helper (HTML + ANSI).

This is the same setup the PRD's flagship user story describes:

    A customer-support RAG bot answers questions from a company knowledge
    base. Elenchus sits between the bot's generated answer and the user.

The demo does not call any LLM — the "bot answers" are hand-crafted
fixtures so detection / false-positive rates are auditable and not just
self-fulfilling (a real bot that gets its own answers right is a broken
benchmark).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from elenchus.config import VerificationConfig
from elenchus.rendering import render_ansi, render_html
from elenchus.types import Verdict
from elenchus.verification_log import InMemoryVerificationLog
from elenchus.verifier import Verifier


# ---------- Synthetic KB ----------------------------------------------------


KB_DOCUMENTS: List[Tuple[str, str]] = [
    (
        "kb-returns",
        "Customers can return any item within 30 days of purchase for a full "
        "refund. Items must be in their original packaging with the receipt "
        "attached. Return shipping is free for defective items; otherwise the "
        "customer pays return shipping. Refunds are issued to the original "
        "payment method within 5 business days of receiving the return.",
    ),
    (
        "kb-shipping",
        "Standard shipping takes 3 to 5 business days within the continental "
        "United States. Express shipping takes 1 to 2 business days and costs "
        "an additional $15. We currently ship only to US addresses; "
        "international orders are not supported at this time. Tracking "
        "information is emailed once the order ships.",
    ),
    (
        "kb-warranty",
        "All electronics carry a 1-year manufacturer warranty covering "
        "manufacturing defects. The warranty does not cover accidental "
        "damage, water damage, or unauthorized modifications. To make a "
        "warranty claim, contact support@example.com with your order number "
        "and a photo of the defect.",
    ),
]


# ---------- Bot answers ------------------------------------------------------


@dataclass
class BotAnswer:
    question: str
    answer: str
    is_hallucinated: bool  # ground truth, used only for metric computation


# 5 bot answers: a mix of clean and hallucinated. The "hallucinated" ones
# invent specific facts that contradict the KB.
BOT_ANSWERS: List[BotAnswer] = [
    BotAnswer(
        question="How long do I have to return an item?",
        answer=(
            "Customers can return any item within 30 days of purchase for a full "
            "refund. Items must be in their original packaging with the "
            "receipt attached."
        ),
        is_hallucinated=False,
    ),
    BotAnswer(
        question="How long does standard shipping take?",
        answer=(
            "Standard shipping takes 1 to 2 business days within the continental "
            "United States. Express shipping costs an additional $15 and also "
            "takes 1 to 2 business days."
        ),
        is_hallucinated=True,  # KB says 3-5 days, bot says 1-2
    ),
    BotAnswer(
        question="Do you ship internationally?",
        answer=(
            "Yes, we ship to most countries worldwide. Standard international "
            "shipping takes 5 to 10 business days and costs an additional $25."
        ),
        is_hallucinated=True,  # KB says "international orders are not supported"
    ),
    BotAnswer(
        question="What is the warranty on electronics?",
        answer=(
            "All electronics carry a 1-year manufacturer warranty covering "
            "manufacturing defects. To make a warranty claim, contact "
            "support@example.com with your order number and a photo of the "
            "defect."
        ),
        is_hallucinated=False,
    ),
    BotAnswer(
        question="How long do refunds take?",
        answer=(
            "Refunds are issued to the original payment method within 5 "
            "business days of receiving the return. Return shipping is free "
            "for all returns, including non-defective items."
        ),
        is_hallucinated=True,  # KB says return shipping is free ONLY for defective items
    ),
]


# ---------- Demo runner -----------------------------------------------------


def _verdict_for_case(case: BotAnswer, cfg: VerificationConfig) -> List[Verdict]:
    log = InMemoryVerificationLog()
    verifier = Verifier(config=cfg, log=log)
    return verifier.verify(output_text=case.answer, source_documents=KB_DOCUMENTS)


def run_demo() -> int:
    print("=" * 72)
    print("Elenchus — flagship customer-support demo (Phase 3)")
    print("=" * 72)

    cfg = VerificationConfig(confidence_gap_threshold=0.15)

    per_case: List[Tuple[BotAnswer, List[Verdict]]] = []
    for case in BOT_ANSWERS:
        verdicts = _verdict_for_case(case, cfg)
        per_case.append((case, verdicts))

    # Per-case details.
    for i, (case, verdicts) in enumerate(per_case, 1):
        print(
            f"\n--- Case {i}: {case.question!r} (hallucinated={case.is_hallucinated}) ---"
        )
        for v in verdicts:
            label = v.label
            tag = (
                "!!"
                if v.label == "contradicted"
                else ("?" if v.label == "unverifiable" else "OK")
            )
            print(
                f"  [{tag}] {label:<13} conf={v.confidence:.2f}  "
                f"tier={v.tier:<9}  claim={v.claim.text!r}"
            )
            if v.evidence is not None:
                # Show first 80 chars of evidence text.
                ev = (
                    v.evidence.text
                    if len(v.evidence.text) <= 80
                    else v.evidence.text[:77] + "..."
                )
                print(f"      evidence: {ev!r}")

    # Aggregate detection / false-positive rates.
    tp = fp = tn = fn = 0
    for case, verdicts in per_case:
        # A case is "caught" if any of its claims is contradicted.
        caught = any(v.label == "contradicted" for v in verdicts)
        if case.is_hallucinated and caught:
            tp += 1
        elif case.is_hallucinated and not caught:
            fn += 1
        elif not case.is_hallucinated and caught:
            fp += 1
        else:
            tn += 1

    print("\n" + "=" * 72)
    print("Aggregate metrics (case-level: did we flag ANY claim?)")
    print("=" * 72)
    print(f"  true positives  (caught hallucination)    : {tp}/{tp + fn}")
    print(f"  false negatives (missed hallucination)    : {fn}")
    print(f"  true negatives  (clean answer left alone) : {tn}/{tn + fp}")
    print(f"  false positives (clean answer flagged)    : {fp}")
    detection_rate = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    fp_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    print(f"  detection rate : {detection_rate:.1%}")
    print(f"  false-positive : {fp_rate:.1%}")

    # Show one rendered hallucinated case and one rendered clean case.
    _render_example(per_case, title="Hallucinated example (case 2 — shipping)")
    _render_example(per_case, title="Clean example (case 1 — returns)", index=0)

    return 0


def _render_example(
    per_case: List[Tuple[BotAnswer, List[Verdict]]],
    *,
    title: str,
    index: int = 1,
) -> None:
    """Print ANSI + HTML renderings for one demo case."""
    case, verdicts = per_case[index]
    print(f"\n--- Rendered example: {title} ---")
    print(f"  question: {case.question!r}")
    print(f"  ground truth: hallucinated = {case.is_hallucinated}")
    print("  --- ANSI ---")
    print(render_ansi(case.answer, verdicts))
    print("  --- HTML ---")
    print(render_html(case.answer, verdicts))


if __name__ == "__main__":
    raise SystemExit(run_demo())
