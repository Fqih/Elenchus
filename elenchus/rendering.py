"""Minimal rendering helper for Phase 2.

Two outputs from the same input (output_text + list[Verdict]):

    - `render_html(...)` — for embedding in Studio / saving to a file.
    - `render_ansi(...)` — terminal-friendly view you can `cat`.

The claim spans (character offsets) are the source of truth: each verdict's
`claim.span` locates the colored region in the original output text.
"""

from __future__ import annotations

import html
from typing import Iterable, List, Tuple

from elenchus.types import Verdict

# Per-label CSS class used in HTML rendering.
_LABEL_CLASS: dict = {
    "supported": "claim supported",
    "contradicted": "claim contradicted",
    "unverifiable": "claim unverifiable",
}

# Per-label ANSI color codes.
_ANSI: dict = {
    "supported": "\x1b[32m",  # green
    "contradicted": "\x1b[31m",  # red
    "unverifiable": "\x1b[33m",  # yellow
}
_ANSI_RESET = "\x1b[0m"


def _sort_by_start(verdicts: Iterable[Verdict]) -> List[Verdict]:
    return sorted(verdicts, key=lambda v: v.claim.span[0])


def _insert_anchors(
    text: str,
    verdicts: Iterable[Verdict],
    wrap_open,  # Callable[[Verdict], str]
    wrap_close,  # Callable[[Verdict], str]
) -> str:
    """Insert anchor markup around each claim span, joining overlapping or
    out-of-order spans into something that at least round-trips the text
    faithfully even when spans aren't strictly monotonic.

    Implementation: scan the text character by character, tracking which
    claim(s) own the current position. Open/close markers are emitted at
    span boundaries. Empty spans are skipped.
    """
    sorted_v = _sort_by_start(verdicts)
    out: list[str] = []
    pos = 0
    text_len = len(text)
    # We accept that multiple verdicts may end at the same index — keep the
    # last opened one as "active" for the open/close pair.
    open_stack: List[Tuple[Verdict, int]] = []  # (verdict, end_position)

    events: list = []
    for v in sorted_v:
        start, end = v.claim.span
        if start >= end or end > text_len:
            continue
        events.append((start, "open", v))
        events.append((end, "close", v))
    events.sort(key=lambda e: (e[0], 0 if e[1] == "close" else 1))

    for offset, kind, v in events:
        if pos < offset:
            out.append(text[pos:offset])
            pos = offset
        if kind == "open":
            out.append(wrap_open(v))
            open_stack.append((v, v.claim.span[1]))
        else:
            out.append(wrap_close(v))
            if open_stack and open_stack[-1][0] is v:
                open_stack.pop()

    if pos < text_len:
        out.append(text[pos:])
    return "".join(out)


def render_ansi(output_text: str, verdicts: List[Verdict]) -> str:
    """Colorize output text by verdict in the terminal. Evidence excerpt
    appears under each claim as a quoted block indented under it."""
    header_lines = ["Verified output:"]
    header_lines.append(
        _insert_anchors(
            output_text,
            verdicts,
            wrap_open=lambda v: _ANSI.get(v.label, ""),
            wrap_close=lambda _: _ANSI_RESET,
        )
    )
    if any(v.evidence is not None for v in verdicts):
        header_lines.append("")
        header_lines.append("Evidence per claim:")
        for v in _sort_by_start(verdicts):
            tag = _ANSI.get(v.label, "")
            end = _ANSI_RESET
            label = f"{tag}[{v.label.upper()} conf={v.confidence:.2f}]{end}"
            line = f"  {label}  {v.claim.text!r}"
            if v.evidence is not None:
                line += f"\n    evidence: {v.evidence.text!r}"
            header_lines.append(line)
    return "\n".join(header_lines)


def render_html(output_text: str, verdicts: List[Verdict]) -> str:
    """Render `output_text` with claims color-coded by verdict, followed by
    a list of evidence excerpts. Suitable for embedding in a page or saving
    to disk."""
    parts: list[str] = []
    parts.append('<div class="elenchus-output">')
    parts.append(
        _insert_anchors(
            output_text,
            verdicts,
            wrap_open=lambda v: f'<span class="{_LABEL_CLASS.get(v.label, "claim")}">',
            wrap_close=lambda _: "</span>",
        )
    )
    parts.append("</div>")

    parts.append('<ol class="elenchus-evidence">')
    for v in _sort_by_start(verdicts):
        cls = _LABEL_CLASS.get(v.label, "claim")
        title = f"{html.escape(v.label)} (confidence {v.confidence:.2f}, tier {v.tier})"
        parts.append(
            f'  <li><span class="{cls}">{html.escape(v.claim.text)}</span> '
            f"<em>{title}</em>"
        )
        if v.evidence is not None:
            parts.append(f"    <blockquote>{html.escape(v.evidence.text)}</blockquote>")
        parts.append("  </li>")
    parts.append("</ol>")
    return "\n".join(parts)


__all__ = ["render_html", "render_ansi"]
