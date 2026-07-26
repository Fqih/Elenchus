"""Sentence-level claim extraction — Phase 1 acceptance criterion #1:

'claim extraction preserves correct spans'.

If the spans drift, future highlighting is broken. We test span fidelity by
slicing the original text at each span and comparing to the claim text.
"""

from elenchus.claim_extractor import extract_claims


def test_single_sentence_yields_one_claim_with_span() -> None:
    text = "Paris is the capital of France."
    claims = extract_claims(text)
    assert len(claims) == 1
    c = claims[0]
    assert c.text == "Paris is the capital of France."
    assert text[c.span[0] : c.span[1]] == c.text
    assert c.id != ""


def test_two_sentences_yield_two_claims_with_correct_spans() -> None:
    text = "Paris is the capital of France. Berlin is the capital of Germany."
    claims = extract_claims(text)
    assert len(claims) == 2

    first, second = claims
    assert text[first.span[0] : first.span[1]] == first.text
    assert text[second.span[0] : second.span[1]] == second.text
    assert first.text == "Paris is the capital of France."
    assert second.text == "Berlin is the capital of Germany."

    # Spans must not overlap and must cover the relevant slices.
    assert first.span[1] <= second.span[0]


def test_three_sentence_mixed_punctuation() -> None:
    text = "The sky is blue! Grass is green. The sun is round?"
    claims = extract_claims(text)
    assert [c.text for c in claims] == [
        "The sky is blue!",
        "Grass is green.",
        "The sun is round?",
    ]
    for c in claims:
        assert text[c.span[0] : c.span[1]] == c.text


def test_empty_text_returns_no_claims() -> None:
    assert extract_claims("") == []
    assert extract_claims("   \n   ") == []


def test_decimal_does_not_create_a_false_sentence_boundary() -> None:
    text = "Version 2.0 is current. Version 1.9 is obsolete."
    claims = extract_claims(text)
    assert [claim.text for claim in claims] == [
        "Version 2.0 is current.",
        "Version 1.9 is obsolete.",
    ]
