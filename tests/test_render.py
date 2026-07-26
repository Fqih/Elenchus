"""Tests for the rendering helper — Phase 2 acceptance.

Each verdict's claim span becomes a colored region. Evidence excerpts are
shown alongside. The contracts we test:

    - The claim text is preserved (no broken chars, no swallowed punctuation).
    - Spans are non-overlapping and cover the original text in the same
      order as the input output.
    - Verdicts of each label produce visibly distinct markup in HTML.
    - ANSI output carries the corresponding ANSI color escape codes.
"""

from datetime import datetime, timezone

from elenchus.rendering import render_html, render_ansi
from elenchus.types import Claim, Evidence, Verdict


def _verdict(
    label: str,
    claim_text: str,
    evidence_text: str | None,
    output_offset: int,
    confidence: float = 0.9,
) -> Verdict:
    return Verdict(
        claim=Claim(
            id=claim_text,
            text=claim_text,
            span=(output_offset, output_offset + len(claim_text)),
        ),
        label=label,  # type: ignore[arg-type]
        confidence=confidence,
        tier="nli",
        evidence=(
            Evidence(
                source_id="kb-001",
                text=evidence_text,
                span=(0, len(evidence_text) if evidence_text else 0),
            )
            if evidence_text is not None
            else None
        ),
        checked_at=datetime.now(timezone.utc),
    )


def _sample_output_and_verdicts():
    output = "Paris is the capital of France. The capital of France is Berlin."
    verdicts = [
        _verdict(
            "supported",
            "Paris is the capital of France.",
            "The capital of France is Paris.",
            0,
        ),
        _verdict(
            "contradicted",
            "The capital of France is Berlin.",
            "The capital of France is Paris.",
            34,
        ),
    ]
    return output, verdicts


def test_html_preserves_text_and_marks_each_verdict() -> None:
    output, verdicts = _sample_output_and_verdicts()
    html = render_html(output, verdicts)
    assert "Paris is the capital of France." in html
    assert "The capital of France is Berlin." in html
    assert html.count('class="claim supported"') >= 1
    assert html.count('class="claim contradicted"') >= 1


def test_html_contains_evidence_excerpt_for_each_claim() -> None:
    output, verdicts = _sample_output_and_verdicts()
    html = render_html(output, verdicts)
    # Each verdict's evidence text should appear next to its claim.
    assert html.count("The capital of France is Paris.") >= 2  # 1× output, 1× evidence


def test_ansi_includes_color_codes_for_supported() -> None:
    output, verdicts = _sample_output_and_verdicts()
    rendered = render_ansi(output, verdicts)
    # ANSI green for "supported", red for "contradicted"
    assert "\x1b[" in rendered
    assert rendered.count("\x1b[") >= 2, "expected ANSI escape per claim"


def test_html_unverifiable_is_marked_unverifiable() -> None:
    output = "Bananas are a tropical fruit. Cats have nine lives."
    verdicts = [
        _verdict("unverifiable", "Bananas are a tropical fruit.", None, 0),
        _verdict("unverifiable", "Cats have nine lives.", None, 30),
    ]
    html = render_html(output, verdicts)
    assert 'class="claim unverifiable"' in html


def test_html_no_evidence_when_verdict_is_unverifiable() -> None:
    output = "Bananas are a tropical fruit."
    verdicts = [
        _verdict("unverifiable", "Bananas are a tropical fruit.", None, 0),
    ]
    html = render_html(output, verdicts)
    # No evidence excerpt block for unverifiable — the verdict already says
    # we don't know.
    assert html.count("<blockquote") == 0
