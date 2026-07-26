"""Core data shapes. Spec lives in .context/Schema.md.

Each shape here is the exact dataclass declared there — no extra fields,
no behaviors. Logic lives in modules that take these as inputs/outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

Label = Literal["supported", "contradicted", "unverifiable"]
Tier = Literal["nli", "llm_judge"]


@dataclass
class Claim:
    id: str
    text: str
    span: tuple[int, int]  # character offsets in the original output


@dataclass
class Evidence:
    source_id: str
    text: str
    span: tuple[int, int]  # character offsets in the source document


@dataclass
class Verdict:
    claim: Claim
    label: Label
    confidence: float
    tier: Tier
    evidence: Optional[Evidence]
    checked_at: datetime


@dataclass
class LogEntry:
    verdict: Verdict
    logged_at: datetime


__all__ = ["Claim", "Evidence", "Verdict", "LogEntry", "Label", "Tier"]
