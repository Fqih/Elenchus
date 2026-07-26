"""Tests for benchmark/prepare_dataset.py — Phase 3 benchmark prep.

We test the preprocessing logic (RAGTruth JSONL → per-claim Schema.md-shaped
records with gold hallucination labels). The download is a thin wrapper and
is tested by importing the constants, not by hitting the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.prepare_dataset import (
    RAGTRUTH_HALLUCINATION_LABELS,
    HallucinationLabel,
    RagtruthRecord,
    ResponseRecord,
    SourceRecord,
    build_dataset,
    extract_response_sentences,
    filter_quality_good,
    label_sentence_against_hallucinations,
    load_source_info,
    load_responses,
)


# ---------- Fixtures ----------------------------------------------------------


def _write_jsonl(path: Path, rows: list) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


# A synthetic faithful response: every sentence is supported by the source.
_FAITHFUL_RESPONSE = {
    "id": "100",
    "source_id": "src-1",
    "model": "test-model",
    "temperature": 0.0,
    "labels": [],
    "split": "test",
    "quality": "good",
    "response": "Anne Frank died of typhus. She was fifteen years old.",
}

_FAITHFUL_SOURCE = {
    "source_id": "src-1",
    "task_type": "Summary",
    "source": "CNN/DM",
    "source_info": "Anne Frank died of typhus at age fifteen.",
    "prompt": "Summarize.",
}

# A response containing an Evident Conflict (hallucinated year).
_HALLUCINATED_RESPONSE = {
    "id": "200",
    "source_id": "src-2",
    "model": "test-model",
    "temperature": 0.0,
    "labels": [
        {
            "start": 0,
            "end": 21,
            "text": "Anne Frank died in 2022",
            "meta": "EVIDENT CONFLICT — original said 1945",
            "label_type": "Evident Conflict",
            "implicit_true": False,
            "due_to_null": False,
        }
    ],
    "split": "test",
    "quality": "good",
    "response": "Anne Frank died in 2022 in Bergen-Belsen.",
}

_HALLUCINATED_SOURCE = {
    "source_id": "src-2",
    "task_type": "Summary",
    "source": "CNN/DM",
    "source_info": "Anne Frank died of typhus in 1945 in Bergen-Belsen.",
    "prompt": "Summarize.",
}

_TRUNCATED_RESPONSE = {
    "id": "300",
    "source_id": "src-3",
    "model": "test-model",
    "temperature": 0.0,
    "labels": [],
    "split": "test",
    "quality": "truncated",  # should be filtered out
    "response": "Anne Frank was a diarist.",
}

_TRUNCATED_SOURCE = {
    "source_id": "src-3",
    "task_type": "Summary",
    "source": "X",
    "source_info": "Anne Frank was a diarist.",
    "prompt": "Summarize.",
}


# ---------- Sentence splitting -----------------------------------------------


def test_extract_response_sentences_returns_non_empty_for_typical_input() -> None:
    text = "Anne Frank died of typhus. She was fifteen years old."
    spans = extract_response_sentences(text)
    assert len(spans) == 2
    for start, end, sent in spans:
        assert text[start:end] == sent, f"span round-trip failed for {sent!r}"


def test_extract_response_sentences_handles_long_input() -> None:
    text = "First sentence here. Second sentence here. Third one."
    spans = extract_response_sentences(text)
    assert len(spans) == 3
    assert text[spans[0][0] : spans[0][1]] == "First sentence here."
    assert text[spans[1][0] : spans[1][1]] == "Second sentence here."
    assert text[spans[2][0] : spans[2][1]] == "Third one."


def test_extract_response_sentences_handles_no_terminator() -> None:
    # If there's no sentence-ending punctuation, return the whole thing as
    # a single span — better than dropping the claim.
    spans = extract_response_sentences("Anne Frank died of typhus")
    assert len(spans) == 1
    assert spans[0][2] == "Anne Frank died of typhus"


def test_extract_response_sentences_matches_library_decimal_boundaries() -> None:
    spans = extract_response_sentences(
        "Version 2.0 is current. Version 1.9 is obsolete."
    )
    assert [sentence for _start, _end, sentence in spans] == [
        "Version 2.0 is current.",
        "Version 1.9 is obsolete.",
    ]


# ---------- Sentence labeling against hallucination spans --------------------


def test_label_sentence_no_overlap_is_supported() -> None:
    spans = [(0, 21, "Anne Frank died in 2022")]  # one sentence
    hallucinations: list[HallucinationLabel] = [
        HallucinationLabel(start=50, end=60, text="...", label_type="Evident Conflict")
    ]
    labels = label_sentence_against_hallucinations(spans, hallucinations)
    assert labels == ["supported"]


def test_label_sentence_full_overlap_with_conflict_is_contradicted() -> None:
    spans = [(0, 21, "Anne Frank died in 2022")]
    hallucinations: list[HallucinationLabel] = [
        HallucinationLabel(
            start=0,
            end=21,
            text="Anne Frank died in 2022",
            label_type="Evident Conflict",
        )
    ]
    labels = label_sentence_against_hallucinations(spans, hallucinations)
    assert labels == ["contradicted"]


def test_label_sentence_overlap_with_baseless_info_is_unverifiable() -> None:
    spans = [(0, 25, "The museum issued a new statement")]
    hallucinations: list[HallucinationLabel] = [
        HallucinationLabel(
            start=0,
            end=25,
            text="The museum issued a new statement",
            label_type="Evident Baseless Info",
        )
    ]
    labels = label_sentence_against_hallucinations(spans, hallucinations)
    assert labels == ["unverifiable"]


def test_label_sentence_partial_overlap_counts_as_contradicted() -> None:
    # The hallucination only covers part of the sentence.
    spans = [(0, 30, "Anne Frank died in 2022 in Bergen-Belsen.")]
    hallucinations: list[HallucinationLabel] = [
        HallucinationLabel(
            start=0,
            end=21,
            text="Anne Frank died in 2022",
            label_type="Evident Conflict",
        )
    ]
    labels = label_sentence_against_hallucinations(spans, hallucinations)
    # The sentence contains a contradicted span → the whole sentence is contradicted.
    assert labels == ["contradicted"]


def test_label_sentence_excludes_unverifiable_hallucination_categories() -> None:
    # If a label type is not in RAGTRUTH_HALLUCINATION_LABELS, treat the
    # sentence as supported — we only count real hallucinations.
    spans = [(0, 10, "Some text.")]
    other = HallucinationLabel(
        start=0, end=10, text="Some text.", label_type="Something Else"
    )
    assert other.label_type not in RAGTRUTH_HALLUCINATION_LABELS
    labels = label_sentence_against_hallucinations(spans, [other])
    assert labels == ["supported"]


# ---------- JSONL loaders -----------------------------------------------------


def test_load_responses_parses_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "responses.jsonl"
    _write_jsonl(p, [_FAITHFUL_RESPONSE, _HALLUCINATED_RESPONSE])
    out = load_responses(str(p))
    assert len(out) == 2
    assert isinstance(out[0], ResponseRecord)
    assert out[0].id == "100"
    assert out[1].labels[0].label_type == "Evident Conflict"


def test_load_source_info_parses_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "sources.jsonl"
    _write_jsonl(p, [_FAITHFUL_SOURCE, _HALLUCINATED_SOURCE])
    out = load_source_info(str(p))
    assert len(out) == 2
    assert isinstance(out[0], SourceRecord)
    assert out[0].source_id == "src-1"


# ---------- Quality filtering ------------------------------------------------


def test_filter_quality_good_keeps_only_quality_good() -> None:
    records = [
        ResponseRecord.from_dict(_FAITHFUL_RESPONSE),
        ResponseRecord.from_dict(_TRUNCATED_RESPONSE),
    ]
    out = filter_quality_good(records)
    assert len(out) == 1
    assert out[0].id == "100"


# ---------- Dataset assembly -------------------------------------------------


def test_build_dataset_emits_one_row_per_sentence(tmp_path: Path) -> None:
    responses = [
        ResponseRecord.from_dict(_FAITHFUL_RESPONSE),
        ResponseRecord.from_dict(_HALLUCINATED_RESPONSE),
    ]
    sources = [
        SourceRecord.from_dict(_FAITHFUL_SOURCE),
        SourceRecord.from_dict(_HALLUCINATED_SOURCE),
    ]
    rows = build_dataset(responses=responses, sources=sources)
    # 2 sentences in faithful + 1 sentence in hallucinated → 3 rows
    assert len(rows) == 3
    labels = [r.gold_label for r in rows]
    assert labels.count("supported") == 2
    assert labels.count("contradicted") == 1


def test_build_dataset_skips_responses_without_source() -> None:
    """A response whose source_id isn't in the source dict should be skipped,
    not crashed on."""
    orphan = {
        "id": "999",
        "source_id": "does-not-exist",
        "model": "x",
        "temperature": 0.0,
        "labels": [],
        "split": "test",
        "quality": "good",
        "response": "Some text.",
    }
    responses = [
        ResponseRecord.from_dict(_FAITHFUL_RESPONSE),
        ResponseRecord.from_dict(orphan),
    ]
    sources = [SourceRecord.from_dict(_FAITHFUL_SOURCE)]
    rows = build_dataset(responses=responses, sources=sources)
    assert len(rows) == 2
    assert all(r.source_id == "src-1" for r in rows)


def test_build_dataset_row_has_required_fields() -> None:
    responses = [ResponseRecord.from_dict(_FAITHFUL_RESPONSE)]
    sources = [SourceRecord.from_dict(_FAITHFUL_SOURCE)]
    rows = build_dataset(responses=responses, sources=sources)
    r = rows[0]
    assert r.response_id == "100"
    assert r.source_id == "src-1"
    assert r.gold_label in {"supported", "contradicted"}
    assert r.claim_text  # non-empty
    assert r.source_text  # non-empty
    assert r.claim_span_in_response[0] < r.claim_span_in_response[1]


# ---------- End-to-end on the real downloaded JSONL --------------------------


@pytest.mark.skipif(
    not Path("benchmark/data/response.jsonl").exists(),
    reason="RAGTruth response.jsonl not downloaded; run prepare_dataset.main first",
)
def test_real_jsonl_loads_with_expected_record_count() -> None:
    records = load_responses("benchmark/data/response.jsonl")
    assert len(records) > 1000, "expected RAGTruth to have thousands of responses"
    sample = records[0]
    assert isinstance(sample, ResponseRecord)
    # At least one record should have at least one label.
    assert any(len(r.labels) > 0 for r in records), (
        "expected some hallucinated responses"
    )


@pytest.mark.skipif(
    not Path("benchmark/data/source_info.jsonl").exists(),
    reason="RAGTruth source_info.jsonl not downloaded",
)
def test_real_source_info_loads() -> None:
    records = load_source_info("benchmark/data/source_info.jsonl")
    assert len(records) > 100
    assert isinstance(records[0], SourceRecord)


def test_ragtruth_record_is_exported() -> None:
    # Type check that the dataclasses are importable as advertised.
    _ = RagtruthRecord.__name__
