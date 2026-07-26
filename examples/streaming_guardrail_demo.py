"""Streaming guardrail demo — Phase 4 acceptance.

Simulates a token stream from a customer-support RAG bot. The bot's
answer is fed token-by-token into a `StreamingVerifier`. As soon as a
`contradicted` claim is detected, the guardrail halts: the rest of the
stream is dropped, the partial output up to the halt point is what the
user sees, and the verdict for the contradicted claim is logged with
its evidence.

This is the streaming version of the flagship demo. The acceptance
    criterion (Plan.md Phase 4) is: the streaming example detects and halts
on an injected contradiction mid-stream.

The demo does not call an LLM. The "bot" is a fixed script that emits
three sentences — the first of which contradicts the source. We use
the real NLI model so the contradiction detection is real, not stubbed.
"""

from __future__ import annotations

import sys
import time
from typing import List

from elenchus.config import VerificationConfig
from elenchus.streaming import StreamingVerifier
from elenchus.verification_log import InMemoryVerificationLog
from elenchus.verifier import Verifier


# Source knowledge base (the "company documents" the bot is grounded in).
KB_DOCUMENTS: List = [
    (
        "kb-shipping",
        "Standard shipping takes 3 to 5 business days within the continental "
        "United States. Express shipping takes 1 to 2 business days and costs "
        "an additional $15. We currently ship only to US addresses; "
        "international orders are not supported at this time.",
    ),
]


# The simulated bot output. Notice sentence 2 contradicts the KB
# ("1 to 2 business days" for standard shipping when the KB says 3 to 5).
BOT_SCRIPT: str = (
    "Standard shipping takes 1 to 2 business days within the continental "
    "United States. "
    "Express shipping takes 1 to 2 business days and costs an additional "
    "$15. "
    "We ship to US addresses only."
)


# Tokenize the bot output into word-like chunks so the streaming API
# is exercised properly (not just one big feed call).
def _tokenize(text: str) -> List[str]:
    tokens: List[str] = []
    word = ""
    for ch in text:
        if ch == " ":
            if word:
                tokens.append(word + " ")
                word = ""
        else:
            word += ch
    if word:
        tokens.append(word)
    return tokens


def _print_token(token: str) -> None:
    sys.stdout.write(token)
    sys.stdout.flush()


def main() -> int:
    print("=" * 70)
    print("Elenchus — streaming guardrail demo (Phase 4)")
    print("=" * 70)
    print(f"\nSource KB:\n  {KB_DOCUMENTS[0][1]}\n")
    print("Streaming bot output (live):\n  ", end="", flush=True)

    log = InMemoryVerificationLog()
    cfg = VerificationConfig(confidence_gap_threshold=0.15)
    verifier = Verifier(config=cfg, log=log)
    sv = StreamingVerifier(
        verifier=verifier,
        log=log,
        source_documents=KB_DOCUMENTS,
    )

    halted_at: int | None = None
    emitted_tokens = 0
    for tok in _tokenize(BOT_SCRIPT):
        if sv.should_halt():
            if halted_at is None:
                halted_at = emitted_tokens
                print("\n\n  >>> HALT: contradicted claim detected <<<", flush=True)
            break
        _print_token(tok)
        sv.add_token(tok)
        emitted_tokens += 1
        # Tiny delay so the streaming illusion is visible.
        time.sleep(0.02)

    sv.finish()
    verdicts = sv.verdicts()

    print("\n\nVerdicts produced during stream:")
    for i, v in enumerate(verdicts, 1):
        marker = (
            "!!"
            if v.label == "contradicted"
            else ("?" if v.label == "unverifiable" else "OK")
        )
        print(
            f"  [{marker}] #{i}  {v.label:<13}  conf={v.confidence:.2f}  "
            f"tier={v.tier}  claim={v.claim.text!r}"
        )
        if v.evidence is not None:
            print(f"      evidence: {v.evidence.text!r}")

    contradicted = [v for v in verdicts if v.label == "contradicted"]
    print(f"\nTotal verdicts logged : {len(verdicts)}")
    print(f"Contradicted verdicts  : {len(contradicted)}")
    print(f"Halt triggered         : {sv.should_halt()}")
    print(f"Halt point (tokens)    : {halted_at if halted_at is not None else 'never'}")

    print("\nVerification Log entries (Rule 4):")
    for entry in log.entries():
        v = entry.verdict
        print(f"  - {entry.logged_at.isoformat()}  {v.label:<13}  {v.claim.text!r}")

    print()
    return 0 if len(contradicted) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
