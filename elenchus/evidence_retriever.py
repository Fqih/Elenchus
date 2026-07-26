"""Deterministic, local evidence retrieval.

All source chunks are enumerated first, then ranked against the claim with a
lightweight lexical score. This keeps retrieval local and deterministic while
preventing ``max_evidence_passages_per_claim`` from silently selecting only the
first document in a multi-document source set.

Chunking strategy, in order:
    1. Paragraph boundaries (blank lines) when present
    2. Single newlines when present
    3. Sentence boundaries (`.`, `!`, `?` followed by whitespace/EOL) as a
       fallback so a single-paragraph source still produces per-sentence
       candidates the NLI model can score meaningfully.
"""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from elenchus.config import VerificationConfig
from elenchus.types import Claim, Evidence

_BLANK_LINE_RE = re.compile(r"\n\s*\n")
_SINGLE_NEWLINE_RE = re.compile(r"\n+")
# Zero-width match: position immediately after a sentence terminator.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])(?=\s|$)")
_TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?|\d+(?:[.,]\d+)*", re.UNICODE)
_PREFIX_MATCH_WEIGHT = 0.65
_COVERAGE_WEIGHT = 0.8
_DENSITY_WEIGHT = 0.2
_NUMERIC_MATCH_BONUS = 0.15
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
    }
)


def _chunk_source(text: str) -> List[Tuple[int, int, str]]:
    """Yield (raw_start, raw_end, raw_chunk) covering every chunk of `text`."""
    if not text or not text.strip():
        return []

    if "\n\n" in text or "\r\n\r\n" in text:
        structural_chunks = _split_by(text, _BLANK_LINE_RE)
    elif "\n" in text:
        structural_chunks = _split_by(text, _SINGLE_NEWLINE_RE)
    else:
        structural_chunks = [(0, len(text), text)]

    # NLI works best on focused premises. Split paragraphs/lines into sentence
    # chunks as well; adjacent windows are reconstructed later for compound
    # claims that need more than one sentence.
    chunks: List[Tuple[int, int, str]] = []
    for structural_start, _structural_end, structural_text in structural_chunks:
        sentence_chunks = _split_by_sentences(structural_text)
        if not sentence_chunks:
            continue
        for sentence_start, sentence_end, sentence_text in sentence_chunks:
            chunks.append(
                (
                    structural_start + sentence_start,
                    structural_start + sentence_end,
                    sentence_text,
                )
            )
    return chunks


def _split_by(text: str, sep_re: "re.Pattern[str]") -> List[Tuple[int, int, str]]:
    chunks: List[Tuple[int, int, str]] = []
    cursor = 0
    for m in sep_re.finditer(text):
        if m.start() > cursor:
            chunks.append((cursor, m.start(), text[cursor : m.start()]))
        cursor = m.end()
    if cursor < len(text):
        chunks.append((cursor, len(text), text[cursor:]))
    return chunks


def _split_by_sentences(text: str) -> List[Tuple[int, int, str]]:
    chunks: List[Tuple[int, int, str]] = []
    cursor = 0
    for m in _SENTENCE_END_RE.finditer(text):
        boundary = m.end()  # zero-width match → position right after terminator
        chunks.append((cursor, boundary, text[cursor:boundary]))
        cursor = boundary
    if cursor < len(text):
        chunks.append((cursor, len(text), text[cursor:]))
    return chunks


def _normalise_term(term: str) -> str:
    """Apply a deliberately small English inflection normaliser.

    This is not intended to be a linguistic stemmer. It only makes common
    variants such as ``ships/shipping`` and ``defect/defective`` more likely to
    rank together before the NLI model performs the semantic decision.
    """
    term = term.casefold()
    if term.isdigit():
        return term
    if len(term) > 5 and term.endswith("ies"):
        return term[:-3] + "y"
    if len(term) > 5 and term.endswith("ing"):
        return term[:-3]
    if len(term) > 4 and term.endswith("ed"):
        return term[:-2]
    if len(term) > 4 and term.endswith("es") and not term.endswith("ses"):
        return term[:-2]
    if len(term) > 3 and term.endswith("s") and not term.endswith("ss"):
        return term[:-1]
    return term


def _content_terms(text: str) -> set[str]:
    return {
        normalised
        for token in _TOKEN_RE.findall(text)
        if token.casefold() not in _STOPWORDS
        if (normalised := _normalise_term(token))
    }


def lexical_relevance(claim_text: str, passage_text: str) -> float:
    """Return a stable relevance score used only to order NLI candidates."""
    query = _content_terms(claim_text)
    passage = _content_terms(passage_text)
    if not query or not passage:
        return 0.0

    exact = query & passage
    unmatched_query = query - exact
    unmatched_passage = passage - exact

    # Prefix matching handles nearby inflections that the intentionally tiny
    # normaliser does not collapse (e.g. visit/visitor, defect/defective).
    prefix_matches = 0
    for query_term in unmatched_query:
        if len(query_term) < 4:
            continue
        if any(
            len(passage_term) >= 4
            and (
                query_term.startswith(passage_term)
                or passage_term.startswith(query_term)
            )
            for passage_term in unmatched_passage
        ):
            prefix_matches += 1

    matched_weight = float(len(exact)) + (_PREFIX_MATCH_WEIGHT * prefix_matches)
    coverage = matched_weight / len(query)
    density = matched_weight / len(passage)

    # Exact numeric agreement is especially informative for the support-bot
    # and RAGTruth domains, while still leaving the NLI model to decide whether
    # the relationship is support or contradiction.
    query_numbers = {term for term in query if any(ch.isdigit() for ch in term)}
    numeric_bonus = (
        _NUMERIC_MATCH_BONUS if query_numbers and query_numbers & passage else 0.0
    )
    return (_COVERAGE_WEIGHT * coverage) + (_DENSITY_WEIGHT * density) + numeric_bonus


def retrieve_evidence(
    claim: Claim,
    source_documents: Sequence[Tuple[str, str]],
    config: VerificationConfig,
) -> List[Evidence]:
    """Return the most relevant configured number of Evidence candidates.

    ``source_documents`` is a sequence of ``(source_id, text)`` pairs. Every
    chunk is considered before the deterministic ranking is applied, so a
    relevant later document cannot be excluded merely because earlier
    documents filled the candidate limit.
    """
    max_chunks = max(0, config.max_evidence_passages_per_claim)
    if max_chunks == 0:
        return []

    candidates: List[tuple[float, int, Evidence]] = []
    insertion_index = 0
    for source_id, src in source_documents:
        chunks = _chunk_source(src)
        max_window = max(1, config.max_evidence_window_chunks)
        for window_start in range(len(chunks)):
            for window_size in range(1, max_window + 1):
                window_end = window_start + window_size
                if window_end > len(chunks):
                    break
                first_start, _first_end, first_raw = chunks[window_start]
                _last_start, last_end, _last_raw = chunks[window_end - 1]
                leading_ws = len(first_raw) - len(first_raw.lstrip())
                span_start = first_start + leading_ws
                raw_window = src[span_start:last_end]
                stripped = raw_window.rstrip()
                if not stripped:
                    continue
                evidence = Evidence(
                    source_id=source_id,
                    text=stripped,
                    span=(span_start, span_start + len(stripped)),
                )
                candidates.append(
                    (
                        lexical_relevance(claim.text, stripped),
                        insertion_index,
                        evidence,
                    )
                )
                insertion_index += 1

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [evidence for _score, _index, evidence in candidates[:max_chunks]]


__all__ = ["retrieve_evidence", "lexical_relevance", "_chunk_source"]
