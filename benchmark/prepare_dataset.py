"""RAGTruth preprocessing for the Phase 3 benchmark.

Reads the official RAGTruth JSONL files and produces per-sentence claim rows
with gold labels (`supported` / `contradicted` / `unverifiable`) suitable for evaluating
Elenchus against.

Input files (downloaded from github.com/ParticleMedia/RAGTruth):
    - response.jsonl   — LLM responses with hallucination span labels
    - source_info.jsonl — context documents used as RAG input

Output:
    - A JSONL file where each line is one sentence-level claim from one
      response, joined with its source document and gold label.

Mapping decisions, made explicit so the benchmark stays auditable:

    - `Evident Conflict` maps to `contradicted`.
    - `Evident Baseless Info` and `Subtle Baseless Info` map to
      `unverifiable`: the source does not support them, but does not
      necessarily assert their opposite.
    - Other label types (none in RAGTruth today) are ignored.
    - `implicit_true=true` keeps the semantic label implied by its
      `label_type` and is also preserved as metadata for the separate
      disputed-case stress slice.
    - `quality != "good"` records are filtered out.
    - Responses whose source_id isn't found in source_info are skipped
      (the benchmark can't evaluate them).

Run as a script to download the dataset and emit a `dataset.jsonl` next to
the source files.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# RAGTruth label types that mark a sentence as hallucinated. Their semantic
# mapping is handled below: conflict -> contradicted, baseless -> unverifiable.
# If the taxonomy grows, this allow-list and mapping must be reviewed together.
RAGTRUTH_HALLUCINATION_LABELS = frozenset(
    {
        "Evident Conflict",
        "Evident Baseless Info",
        "Subtle Baseless Info",
    }
)

# Raw GitHub URLs for the official RAGTruth dataset.
RAGTRUTH_RESPONSES_URL = "https://raw.githubusercontent.com/ParticleMedia/RAGTruth/main/dataset/response.jsonl"
RAGTRUTH_SOURCES_URL = "https://raw.githubusercontent.com/ParticleMedia/RAGTruth/main/dataset/source_info.jsonl"


# ---------- Data shapes ------------------------------------------------------


@dataclass(frozen=True)
class HallucinationLabel:
    start: int
    end: int
    text: str
    label_type: str
    implicit_true: bool = False
    due_to_null: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "HallucinationLabel":
        return cls(
            start=int(d["start"]),
            end=int(d["end"]),
            text=str(d.get("text", "")),
            label_type=str(d["label_type"]),
            implicit_true=bool(d.get("implicit_true", False)),
            due_to_null=bool(d.get("due_to_null", False)),
        )


@dataclass
class ResponseRecord:
    id: str
    source_id: str
    model: str
    temperature: float
    labels: List[HallucinationLabel]
    split: str
    quality: str
    response: str

    @classmethod
    def from_dict(cls, d: dict) -> "ResponseRecord":
        labels_raw = d.get("labels", []) or []
        return cls(
            id=str(d["id"]),
            source_id=str(d["source_id"]),
            model=str(d.get("model", "")),
            temperature=float(d.get("temperature", 0.0)),
            labels=[HallucinationLabel.from_dict(x) for x in labels_raw],
            split=str(d.get("split", "")),
            quality=str(d.get("quality", "")),
            response=str(d.get("response", "")),
        )


@dataclass
class SourceRecord:
    source_id: str
    task_type: str
    source: str
    source_info: str
    prompt: str

    @classmethod
    def from_dict(cls, d: dict) -> "SourceRecord":
        info = d.get("source_info", "")
        if not isinstance(info, str):
            info = json.dumps(info)
        return cls(
            source_id=str(d["source_id"]),
            task_type=str(d.get("task_type", "")),
            source=str(d.get("source", "")),
            source_info=info,
            prompt=str(d.get("prompt", "")),
        )


@dataclass
class RagtruthRecord:
    """One row in the prepared benchmark dataset.

    Mirrors the per-claim model Elenchus verifies in production:
    a response sentence, the source document it was generated against,
    and the gold label indicating whether RAGTruth's annotators marked
    it as faithful or hallucinated.
    """

    response_id: str
    source_id: str
    claim_text: str
    claim_span_in_response: Tuple[int, int]
    source_text: str
    gold_label: str  # "supported" | "contradicted" | "unverifiable"
    label_types_in_span: List[str] = field(default_factory=list)
    implicit_true_count: int = 0


# ---------- Sentence splitting -----------------------------------------------


def extract_response_sentences(text: str) -> List[Tuple[int, int, str]]:
    """Split `text` into sentences, returning (start, end, sentence) triples.

    Spans are character offsets into the original `text` and round-trip:
    `text[start:end] == sentence` for every triple.
    """
    from elenchus.claim_extractor import extract_claims

    return [
        (claim.span[0], claim.span[1], claim.text) for claim in extract_claims(text)
    ]


# ---------- Sentence labeling ------------------------------------------------


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def label_sentence_against_hallucinations(
    sentence_spans: List[Tuple[int, int, str]],
    hallucination_labels: List[HallucinationLabel],
) -> List[str]:
    """Return the semantically correct Elenchus gold label per sentence.

    Conflict has precedence over baseless information when multiple annotated
    spans overlap one sentence. Baseless information is `unverifiable`, not
    `contradicted`, because absence from a source is not evidence of the
    opposite claim.
    """
    out: List[str] = []
    for s_start, s_end, _ in sentence_spans:
        overlapping_types: set[str] = set()
        for h in hallucination_labels:
            if h.label_type not in RAGTRUTH_HALLUCINATION_LABELS:
                continue
            if _overlaps(s_start, s_end, h.start, h.end):
                overlapping_types.add(h.label_type)
        if "Evident Conflict" in overlapping_types:
            out.append("contradicted")
        elif overlapping_types:
            out.append("unverifiable")
        else:
            out.append("supported")
    return out


# ---------- JSONL loading ----------------------------------------------------


def load_responses(path: str) -> List[ResponseRecord]:
    out: List[ResponseRecord] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(ResponseRecord.from_dict(json.loads(line)))
    return out


def load_source_info(path: str) -> List[SourceRecord]:
    out: List[SourceRecord] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(SourceRecord.from_dict(json.loads(line)))
    return out


# ---------- Filtering --------------------------------------------------------


def filter_quality_good(records: List[ResponseRecord]) -> List[ResponseRecord]:
    return [r for r in records if r.quality == "good"]


# ---------- Dataset assembly -------------------------------------------------


def build_dataset(
    responses: List[ResponseRecord],
    sources: List[SourceRecord],
) -> List[RagtruthRecord]:
    """Join each response with its source and emit one row per sentence.

    Skips responses whose source_id isn't found.
    """
    src_by_id = {s.source_id: s for s in sources}
    out: List[RagtruthRecord] = []
    for r in responses:
        src = src_by_id.get(r.source_id)
        if src is None:
            continue
        sentence_spans = extract_response_sentences(r.response)
        labels = label_sentence_against_hallucinations(sentence_spans, r.labels)
        for (s_start, s_end, sent), lab in zip(sentence_spans, labels):
            span_label_types = sorted(
                {
                    h.label_type
                    for h in r.labels
                    if h.label_type in RAGTRUTH_HALLUCINATION_LABELS
                    and _overlaps(s_start, s_end, h.start, h.end)
                }
            )
            implicit_true_count = sum(
                1
                for h in r.labels
                if h.label_type in RAGTRUTH_HALLUCINATION_LABELS
                and h.implicit_true
                and _overlaps(s_start, s_end, h.start, h.end)
            )
            out.append(
                RagtruthRecord(
                    response_id=r.id,
                    source_id=r.source_id,
                    claim_text=sent,
                    claim_span_in_response=(s_start, s_end),
                    source_text=src.source_info,
                    gold_label=lab,
                    label_types_in_span=span_label_types,
                    implicit_true_count=implicit_true_count,
                )
            )
    return out


# ---------- Download + write -------------------------------------------------


def download(url: str, dest: Path, timeout: int = 120) -> None:
    """Stream a URL to `dest`. Used by `main()` to fetch RAGTruth files."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "elenchus-benchmark"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)


def write_jsonl(rows: List[RagtruthRecord], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        for row in rows:
            d = {
                "response_id": row.response_id,
                "source_id": row.source_id,
                "claim_text": row.claim_text,
                "claim_span_in_response": list(row.claim_span_in_response),
                "source_text": row.source_text,
                "gold_label": row.gold_label,
                "label_types_in_span": row.label_types_in_span,
                "implicit_true_count": row.implicit_true_count,
            }
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def load_prepared(path: str, limit: Optional[int] = None) -> List[RagtruthRecord]:
    """Inverse of write_jsonl, for the benchmark runner to consume.

    `limit` caps the number of rows loaded — useful when the full dataset
    is hundreds of MB and we only need a stratified subset for the run.
    """
    out: List[RagtruthRecord] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            out.append(
                RagtruthRecord(
                    response_id=d["response_id"],
                    source_id=d["source_id"],
                    claim_text=d["claim_text"],
                    claim_span_in_response=tuple(d["claim_span_in_response"]),
                    source_text=d["source_text"],
                    gold_label=d["gold_label"],
                    label_types_in_span=list(d.get("label_types_in_span", [])),
                    implicit_true_count=int(d.get("implicit_true_count", 0)),
                )
            )
            if limit is not None and len(out) >= limit:
                break
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """Download RAGTruth and write `dataset.jsonl` next to it.

    Skips the download if the files already exist locally.
    """
    data_dir = Path(__file__).parent / "data"
    responses_path = data_dir / "response.jsonl"
    sources_path = data_dir / "source_info.jsonl"
    out_path = data_dir / "dataset.jsonl"

    if not responses_path.exists():
        print(
            f"Downloading {RAGTRUTH_RESPONSES_URL} → {responses_path}", file=sys.stderr
        )
        download(RAGTRUTH_RESPONSES_URL, responses_path)
    if not sources_path.exists():
        print(f"Downloading {RAGTRUTH_SOURCES_URL} → {sources_path}", file=sys.stderr)
        download(RAGTRUTH_SOURCES_URL, sources_path)

    print("Loading RAGTruth JSONL…", file=sys.stderr)
    responses = filter_quality_good(load_responses(str(responses_path)))
    sources = load_source_info(str(sources_path))

    print(f"  responses (quality=good): {len(responses)}", file=sys.stderr)
    print(f"  sources: {len(sources)}", file=sys.stderr)

    rows = build_dataset(responses=responses, sources=sources)
    print(f"  per-sentence rows: {len(rows)}", file=sys.stderr)
    for label in ("supported", "contradicted", "unverifiable"):
        count = sum(1 for row in rows if row.gold_label == label)
        print(f"  {label} rows: {count} ({count / len(rows):.1%})", file=sys.stderr)

    write_jsonl(rows, out_path)
    print(f"Wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
