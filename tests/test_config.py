"""Schema-anchored tests for VerificationConfig. Spec lives in .context/Schema.md."""

from elenchus.config import VerificationConfig


def test_defaults_match_schema() -> None:
    """Schema.md specifies the defaults. They must match exactly."""
    cfg = VerificationConfig()
    assert cfg.confidence_gap_threshold == 0.15
    assert cfg.nli_decision_threshold == 0.50
    assert cfg.nli_model_name == "cross-encoder/nli-deberta-v3-base"
    assert cfg.max_evidence_passages_per_claim == 5
    assert cfg.max_evidence_window_chunks == 4
    assert cfg.llm_judge is None


def test_config_is_frozen() -> None:
    """Mutating a frozen dataclass must raise — Rule 1: single source of truth."""
    cfg = VerificationConfig()
    try:
        cfg.confidence_gap_threshold = 0.99  # type: ignore[misc]
    except Exception as exc:  # FrozenInstanceError is a subclass of AttributeError
        assert "frozen" in type(exc).__name__.lower() or "frozen" in str(exc).lower()
        return
    raise AssertionError("expected frozen config to refuse mutation")
