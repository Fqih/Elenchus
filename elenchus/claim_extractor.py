"""Sentence-level claim extraction with character-offset spans.

v1 uses a regex sentence splitter so the result is deterministic and doesn't
require any model. Span fidelity is the contract: `text[claim.span[0]:claim.span[1]]`
must always equal `claim.text`.
"""

from __future__ import annotations

from elenchus.types import Claim

_SENTENCE_TERMINATORS = frozenset(".!?")


def find_sentence_boundary(text: str, *, final: bool = False) -> int | None:
    """Return the next boundary shared by batch and streaming extraction.

    A punctuation mark is a boundary only when followed by whitespace. A mark
    at the current end of the buffer counts only when ``final=True``; streaming
    callers therefore wait for one character of look-ahead instead of
    prematurely splitting decimals such as ``2.0``.
    """
    for index, char in enumerate(text):
        if char not in _SENTENCE_TERMINATORS:
            continue
        after = index + 1
        if after < len(text) and text[after].isspace():
            return after
        if final and after == len(text):
            return after
    return None


def extract_claims(text: str) -> list[Claim]:
    """Split `text` into sentence-level claims, preserving character offsets.

    Spans are inclusive of the trailing sentence punctuation. Whitespace-only
    input returns an empty list. For every returned claim,
    `text[claim.span[0]:claim.span[1]] == claim.text`.
    """
    if not text or not text.strip():
        return []

    raw_chunks: list[tuple[int, str]] = []  # (raw_start_offset, raw_chunk)
    cursor = 0
    while cursor < len(text):
        relative_boundary = find_sentence_boundary(text[cursor:], final=True)
        if relative_boundary is None:
            break
        boundary = cursor + relative_boundary
        raw_chunks.append((cursor, text[cursor:boundary]))
        cursor = boundary
    if cursor < len(text):
        raw_chunks.append((cursor, text[cursor:]))

    claims: list[Claim] = []
    for i, (raw_start, raw) in enumerate(raw_chunks):
        leading_ws = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if not stripped:
            continue
        start = raw_start + leading_ws
        end = start + len(stripped)
        # Sanity: the slice must round-trip exactly.
        assert text[start:end] == stripped, (start, end, text[start:end], stripped)
        claims.append(Claim(id=f"c{i}", text=stripped, span=(start, end)))
    return claims


__all__ = ["extract_claims", "find_sentence_boundary"]
