"""Phase 1 evidence retrieval: ranks chunks and bounded adjacent windows.

Retrieval remains deterministic and local. It considers every source chunk
before applying the configured candidate limit, and every returned span must
round-trip so Phase 2 highlighting remains exact.
"""

from elenchus.config import VerificationConfig
from elenchus.types import Claim
from elenchus.evidence_retriever import retrieve_evidence


def test_returns_one_evidence_per_chunk_with_correct_spans() -> None:
    src_id = "kb-001"
    src = "Paris is the capital of France.\n\nBerlin is the capital of Germany."
    cfg = VerificationConfig()

    chunks = retrieve_evidence(
        claim=Claim(id="c", text="ignored", span=(0, 7)),
        source_documents=[(src_id, src)],
        config=cfg,
    )

    assert len(chunks) >= 2
    texts = [e.text for e in chunks]
    assert any("Paris is the capital of France." in t for t in texts)
    assert any("Berlin is the capital of Germany." in t for t in texts)

    # Each evidence's slice into its source must equal its stored text.
    for e in chunks:
        assert src[e.span[0] : e.span[1]] == e.text
        assert e.source_id == src_id


def test_respects_max_evidence_passages_per_claim() -> None:
    cfg = VerificationConfig(max_evidence_passages_per_claim=2)
    src = "\n\n".join(f"sentence number {i}." for i in range(5))  # 5 chunks
    chunks = retrieve_evidence(
        claim=Claim(id="c", text="anything", span=(0, 8)),
        source_documents=[("kb", src)],
        config=cfg,
    )
    assert len(chunks) == 2


def test_empty_sources_returns_empty_list() -> None:
    cfg = VerificationConfig()
    assert (
        retrieve_evidence(
            claim=Claim(id="c", text="x", span=(0, 1)),
            source_documents=[],
            config=cfg,
        )
        == []
    )


def test_relevant_later_document_is_ranked_before_earlier_documents() -> None:
    cfg = VerificationConfig(max_evidence_passages_per_claim=2)
    claim = Claim(
        id="c",
        text="All electronics have a one-year manufacturer warranty.",
        span=(0, 57),
    )
    chunks = retrieve_evidence(
        claim=claim,
        source_documents=[
            (
                "returns",
                "Customers may return items in original packaging. "
                "Refunds use the original payment method.",
            ),
            (
                "warranty",
                "All electronics carry a 1-year manufacturer warranty. "
                "The warranty covers manufacturing defects.",
            ),
        ],
        config=cfg,
    )

    assert len(chunks) == 2
    assert chunks[0].source_id == "warranty"
    assert "warranty" in chunks[0].text.lower()


def test_zero_candidate_limit_returns_no_evidence() -> None:
    cfg = VerificationConfig(max_evidence_passages_per_claim=0)
    chunks = retrieve_evidence(
        claim=Claim(id="c", text="A claim.", span=(0, 8)),
        source_documents=[("kb", "Some source text.")],
        config=cfg,
    )
    assert chunks == []


def test_compound_claim_can_retrieve_a_contiguous_multi_sentence_window() -> None:
    source = (
        "The store accepts returns within 30 days. "
        "Items need their original packaging. "
        "Refunds go to the original payment method."
    )
    claim = Claim(
        id="c",
        text=(
            "Returns are accepted within 30 days and refunds go to the original "
            "payment method."
        ),
        span=(0, 85),
    )
    chunks = retrieve_evidence(
        claim=claim,
        source_documents=[("policy", source)],
        config=VerificationConfig(
            max_evidence_passages_per_claim=3,
            max_evidence_window_chunks=3,
        ),
    )

    assert any(
        "30 days" in item.text and "original payment method" in item.text
        for item in chunks
    )
    for item in chunks:
        assert source[item.span[0] : item.span[1]] == item.text
