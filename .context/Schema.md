# Elenchus — Schema

Data shapes only. For component responsibilities, see Architecture.md. For
why these shapes look the way they do, see Design.md.

## Library

```python
@dataclass
class Claim:
    id: str
    text: str
    span: tuple[int, int]        # character offsets in the original output

@dataclass
class Evidence:
    source_id: str
    text: str
    span: tuple[int, int]        # character offsets in the source document

@dataclass
class Verdict:
    claim: Claim
    label: Literal["supported", "contradicted", "unverifiable"]
    confidence: float
    tier: Literal["nli", "llm_judge"]
    evidence: Evidence | None
    checked_at: datetime

@dataclass(frozen=True)
class VerificationConfig:
    confidence_gap_threshold: float = 0.15   # tier-1 -> tier-2 escalation trigger
    nli_decision_threshold: float = 0.50     # minimum entail/contradict probability
    nli_model_name: str = "cross-encoder/nli-deberta-v3-base"
    max_evidence_passages_per_claim: int = 5
    max_evidence_window_chunks: int = 4
    llm_judge: Callable[[Claim, list[Evidence]], Verdict] | None = None
```

## Studio

```python
@dataclass
class Project:
    id: str
    name: str
    source_documents: list[str]   # SourceDocument ids
    created_at: datetime

@dataclass
class SourceDocument:
    id: str
    project_id: str
    name: str
    content: str
    content_sha256: str
    version: int
    created_at: datetime
    updated_at: datetime

@dataclass
class VerificationRun:
    id: str
    project_id: str
    question: str | None
    model_or_prompt_label: str     # for side-by-side comparison
    candidate_answer: str
    source_document_versions: dict[str, int]  # document id -> checked version
    verdicts: list[Verdict]
    gate_result: Literal["allowed", "blocked", "flagged"]
    latency_ms: float
    created_at: datetime

@dataclass(frozen=True)
class GatePolicy:
    block_on_any_contradiction: bool = True
    flag_if_unverifiable_count_exceeds: int = 1

GateResult = Literal["allowed", "blocked", "flagged"]
```

### Output gate precedence

Gate evaluation is deterministic and ordered:

1. Return `blocked` when `block_on_any_contradiction` is enabled and at least
   one verdict is contradicted.
2. Otherwise return `flagged` when the number of unverifiable verdicts is
   greater than `flag_if_unverifiable_count_exceeds`.
3. Otherwise return `allowed`.

This is the required `blocked > flagged > allowed` precedence.

## Verification Log entry (as persisted, in-memory or SQLite)

```python
@dataclass
class LogEntry:
    verdict: Verdict
    logged_at: datetime
```
