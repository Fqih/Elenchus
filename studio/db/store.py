"""SQLite-backed Studio store.

Schema is created on first use. Four tables:

    projects(id, name, created_at)
    source_documents(id, project_id, name, content, content_sha256,
                     version, created_at, updated_at)
    source_document_current(id, project_id, current_version)
    verification_runs(id, project_id, question, model_or_prompt_label,
                      candidate_answer, source_document_versions_json,
                      verdicts_json, gate_result, latency_ms, created_at)
    project_gate_policies(project_id, block_on_any_contradiction,
                          flag_if_unverifiable_count_exceeds, updated_at)

`source_document_versions_json` is a JSON object mapping
`source_document_id -> version_int`. We store it as JSON because the set
of source documents for a project is itself unbounded.

`verdicts_json` is a JSON array of full Verdict objects (claim, label,
confidence, tier, evidence, checked_at). Storing the verdict is what
makes a run reproducible for the audit purpose — even if the underlying
NLI model is swapped out, the verdicts that were actually returned are
preserved.

`project_gate_policies` is Rule 2 honored: the gate policy is configuration
per project, not buried in API code.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from elenchus.types import Claim, Evidence, Verdict

from studio.gate import GatePolicy


# ---------- Public dataclasses ----------------------------------------------


@dataclass
class Project:
    id: str
    name: str
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
    question: Optional[str]
    model_or_prompt_label: str
    candidate_answer: str
    source_document_versions: Dict[str, int]
    verdicts: List[Verdict]
    gate_result: str  # "allowed" | "blocked" | "flagged"
    latency_ms: float
    created_at: datetime
    # Phase 7 fields (nullable / defaults for backward compatibility).
    phase7_retry_stop_reason: Optional[str] = None
    phase7_retry_attempts: int = 0
    phase7_memory_item_ids: List[str] = field(default_factory=list)


# ---------- Helpers ----------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _verdict_to_dict(v: Verdict) -> Dict[str, Any]:
    return {
        "claim": {
            "id": v.claim.id,
            "text": v.claim.text,
            "span": list(v.claim.span),
        },
        "label": v.label,
        "confidence": v.confidence,
        "tier": v.tier,
        "evidence": (
            None
            if v.evidence is None
            else {
                "source_id": v.evidence.source_id,
                "text": v.evidence.text,
                "span": list(v.evidence.span),
            }
        ),
        "checked_at": v.checked_at.isoformat(),
    }


def _verdict_from_dict(d: Dict[str, Any]) -> Verdict:
    claim = Claim(
        id=d["claim"]["id"],
        text=d["claim"]["text"],
        span=(d["claim"]["span"][0], d["claim"]["span"][1]),
    )
    ev_raw = d.get("evidence")
    evidence: Optional[Evidence] = None
    if ev_raw is not None:
        evidence = Evidence(
            source_id=ev_raw["source_id"],
            text=ev_raw["text"],
            span=(ev_raw["span"][0], ev_raw["span"][1]),
        )
    return Verdict(
        claim=claim,
        label=d["label"],  # type: ignore[arg-type]
        confidence=float(d["confidence"]),
        tier=d["tier"],  # type: ignore[arg-type]
        evidence=evidence,
        checked_at=datetime.fromisoformat(d["checked_at"]),
    )


# ---------- Store ------------------------------------------------------------


class StudioStore:
    """SQLite-backed persistence for Project, SourceDocument, VerificationRun."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # `check_same_thread=False` is necessary because FastAPI's
        # TestClient (and any real ASGI server) runs request handlers in
        # a worker thread that is not the same thread that constructed
        # the connection. The studio is a single-process local service
        # (per Design.md), so this is safe.
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_schema()

    # ---- Schema setup ------------------------------------------------------

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_documents (
                    id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (id, version),
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_document_current (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    current_version INTEGER NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS verification_runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    question TEXT,
                    model_or_prompt_label TEXT NOT NULL,
                    candidate_answer TEXT NOT NULL,
                    source_document_versions_json TEXT NOT NULL,
                    verdicts_json TEXT NOT NULL,
                    gate_result TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    phase7_retry_stop_reason TEXT,
                    phase7_retry_attempts INTEGER NOT NULL DEFAULT 0,
                    phase7_memory_item_ids TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_gate_policies (
                    project_id TEXT PRIMARY KEY,
                    block_on_any_contradiction INTEGER NOT NULL,
                    flag_if_unverifiable_count_exceeds INTEGER NOT NULL,
                    phase7_enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
                """
            )
        # Idempotent column-level migration for Phase 7.
        self._migrate_phase7_columns()

    def close(self) -> None:
        self._conn.close()

    def _migrate_phase7_columns(self) -> None:
        """Idempotently add Phase 7 columns to existing rows from Phase 5/6.

        SQLite has no `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. We use
        PRAGMA table_info to detect what's already present and only
        issue ALTER TABLE statements for the missing columns. Safe to
        call on every open.
        """
        runs_cols = {
            row["name"]
            for row in self._conn.execute(
                "PRAGMA table_info(verification_runs)"
            ).fetchall()
        }
        if "phase7_retry_stop_reason" not in runs_cols:
            self._conn.execute(
                "ALTER TABLE verification_runs "
                "ADD COLUMN phase7_retry_stop_reason TEXT"
            )
        if "phase7_retry_attempts" not in runs_cols:
            self._conn.execute(
                "ALTER TABLE verification_runs "
                "ADD COLUMN phase7_retry_attempts INTEGER NOT NULL DEFAULT 0"
            )
        if "phase7_memory_item_ids" not in runs_cols:
            self._conn.execute(
                "ALTER TABLE verification_runs "
                "ADD COLUMN phase7_memory_item_ids TEXT NOT NULL DEFAULT '[]'"
            )

        pol_cols = {
            row["name"]
            for row in self._conn.execute(
                "PRAGMA table_info(project_gate_policies)"
            ).fetchall()
        }
        if "phase7_enabled" not in pol_cols:
            self._conn.execute(
                "ALTER TABLE project_gate_policies "
                "ADD COLUMN phase7_enabled INTEGER NOT NULL DEFAULT 0"
            )

    # ---- Project -----------------------------------------------------------

    def create_project(self, *, name: str) -> Project:
        project_id = str(uuid.uuid4())
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO projects (id, name, created_at) VALUES (?, ?, ?)",
                (project_id, name, now.isoformat()),
            )
        return Project(id=project_id, name=name, created_at=now)

    def get_project(self, project_id: str) -> Project:
        row = self._conn.execute(
            "SELECT id, name, created_at FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"project not found: {project_id}")
        return Project(
            id=row["id"],
            name=row["name"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_projects(self) -> List[Project]:
        rows = self._conn.execute(
            "SELECT id, name, created_at FROM projects ORDER BY created_at ASC"
        ).fetchall()
        return [
            Project(
                id=r["id"],
                name=r["name"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # ---- SourceDocument ----------------------------------------------------

    def add_source_document(
        self, *, project_id: str, name: str, content: str
    ) -> SourceDocument:
        # Validate project exists (FK is not enforced under SQLite defaults).
        self.get_project(project_id)

        doc_id = str(uuid.uuid4())
        now = _now()
        sha = _sha256(content)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO source_documents
                    (id, project_id, name, content, content_sha256,
                     version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (doc_id, project_id, name, content, sha, 1, now.isoformat(), now.isoformat()),
            )
            self._conn.execute(
                """
                INSERT INTO source_document_current (id, project_id, current_version)
                VALUES (?, ?, 1)
                """,
                (doc_id, project_id),
            )
        return SourceDocument(
            id=doc_id,
            project_id=project_id,
            name=name,
            content=content,
            content_sha256=sha,
            version=1,
            created_at=now,
            updated_at=now,
        )

    def update_source_document(
        self, *, source_id: str, new_content: str
    ) -> SourceDocument:
        cur = self._conn.execute(
            "SELECT project_id, current_version FROM source_document_current WHERE id = ?",
            (source_id,),
        ).fetchone()
        if cur is None:
            raise KeyError(f"source document not found: {source_id}")
        next_version = int(cur["current_version"]) + 1
        now = _now()
        sha = _sha256(new_content)
        # We need the previous name to keep the row consistent.
        prev = self._conn.execute(
            "SELECT name FROM source_documents WHERE id = ? AND version = ?",
            (source_id, cur["current_version"]),
        ).fetchone()
        if prev is None:
            raise KeyError(f"source document version missing: {source_id}")
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO source_documents
                    (id, project_id, name, content, content_sha256,
                     version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    cur["project_id"],
                    prev["name"],
                    new_content,
                    sha,
                    next_version,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            self._conn.execute(
                "UPDATE source_document_current SET current_version = ? WHERE id = ?",
                (next_version, source_id),
            )
        return SourceDocument(
            id=source_id,
            project_id=cur["project_id"],
            name=prev["name"],
            content=new_content,
            content_sha256=sha,
            version=next_version,
            created_at=now,
            updated_at=now,
        )

    def get_source_document(
        self, *, source_id: str, version: Optional[int] = None
    ) -> SourceDocument:
        if version is None:
            cur = self._conn.execute(
                "SELECT current_version FROM source_document_current WHERE id = ?",
                (source_id,),
            ).fetchone()
            if cur is None:
                raise KeyError(f"source document not found: {source_id}")
            version = int(cur["current_version"])
        row = self._conn.execute(
            """
            SELECT id, project_id, name, content, content_sha256,
                   version, created_at, updated_at
            FROM source_documents
            WHERE id = ? AND version = ?
            """,
            (source_id, version),
        ).fetchone()
        if row is None:
            raise KeyError(
                f"source document version not found: {source_id} v{version}"
            )
        return SourceDocument(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"],
            content=row["content"],
            content_sha256=row["content_sha256"],
            version=int(row["version"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_source_documents(self, *, project_id: str) -> List[SourceDocument]:
        rows = self._conn.execute(
            """
            SELECT sd.id, sd.project_id, sd.name, sd.content, sd.content_sha256,
                   sd.version, sd.created_at, sd.updated_at
            FROM source_documents sd
            JOIN source_document_current cur ON cur.id = sd.id
            WHERE sd.project_id = ? AND sd.version = cur.current_version
            ORDER BY sd.created_at ASC
            """,
            (project_id,),
        ).fetchall()
        return [
            SourceDocument(
                id=r["id"],
                project_id=r["project_id"],
                name=r["name"],
                content=r["content"],
                content_sha256=r["content_sha256"],
                version=int(r["version"]),
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
            )
            for r in rows
        ]

    # ---- VerificationRun ---------------------------------------------------

    def record_run(
        self,
        *,
        project_id: str,
        question: Optional[str],
        model_or_prompt_label: str,
        candidate_answer: str,
        source_versions: Dict[str, int],
        verdicts: List[Verdict],
        gate_result: str,
        latency_ms: float,
        phase7_retry_stop_reason: Optional[str] = None,
        phase7_retry_attempts: int = 0,
        phase7_memory_item_ids: Optional[List[str]] = None,
    ) -> VerificationRun:
        # Validate project exists.
        self.get_project(project_id)
        run_id = str(uuid.uuid4())
        now = _now()
        memory_item_ids = phase7_memory_item_ids or []
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO verification_runs
                    (id, project_id, question, model_or_prompt_label,
                     candidate_answer, source_document_versions_json,
                     verdicts_json, gate_result, latency_ms, created_at,
                     phase7_retry_stop_reason, phase7_retry_attempts,
                     phase7_memory_item_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    project_id,
                    question,
                    model_or_prompt_label,
                    candidate_answer,
                    json.dumps(source_versions),
                    json.dumps([_verdict_to_dict(v) for v in verdicts]),
                    gate_result,
                    float(latency_ms),
                    now.isoformat(),
                    phase7_retry_stop_reason,
                    int(phase7_retry_attempts),
                    json.dumps(memory_item_ids),
                ),
            )
        return VerificationRun(
            id=run_id,
            project_id=project_id,
            question=question,
            model_or_prompt_label=model_or_prompt_label,
            candidate_answer=candidate_answer,
            source_document_versions=dict(source_versions),
            verdicts=list(verdicts),
            gate_result=gate_result,
            latency_ms=float(latency_ms),
            created_at=now,
            phase7_retry_stop_reason=phase7_retry_stop_reason,
            phase7_retry_attempts=int(phase7_retry_attempts),
            phase7_memory_item_ids=list(memory_item_ids),
        )

    def get_run(self, run_id: str) -> VerificationRun:
        row = self._conn.execute(
            """
            SELECT id, project_id, question, model_or_prompt_label,
                   candidate_answer, source_document_versions_json,
                   verdicts_json, gate_result, latency_ms, created_at,
                   phase7_retry_stop_reason, phase7_retry_attempts,
                   phase7_memory_item_ids
            FROM verification_runs WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"run not found: {run_id}")
        return _run_from_row(row)

    def list_runs(self, *, project_id: str) -> List[VerificationRun]:
        rows = self._conn.execute(
            """
            SELECT id, project_id, question, model_or_prompt_label,
                   candidate_answer, source_document_versions_json,
                   verdicts_json, gate_result, latency_ms, created_at,
                   phase7_retry_stop_reason, phase7_retry_attempts,
                   phase7_memory_item_ids
            FROM verification_runs
            WHERE project_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (project_id,),
        ).fetchall()
        return [_run_from_row(r) for r in rows]

    def update_run_phase7(
        self,
        *,
        run_id: str,
        phase7_retry_stop_reason: Optional[str],
        phase7_retry_attempts: int,
        phase7_memory_item_ids: List[str],
    ) -> None:
        """Persist Phase 7 integration outputs onto an existing run row.

        The /checks handler records the run before invoking Phase 7
        integrations (so the run_id is available to tag Lethe memory
        items). This method is called after the integrations complete
        to persist their outputs back onto the run.
        """
        with self._conn:
            self._conn.execute(
                """
                UPDATE verification_runs SET
                    phase7_retry_stop_reason = ?,
                    phase7_retry_attempts = ?,
                    phase7_memory_item_ids = ?
                WHERE id = ?
                """,
                (
                    phase7_retry_stop_reason,
                    int(phase7_retry_attempts),
                    json.dumps(list(phase7_memory_item_ids)),
                    run_id,
                ),
            )

    # ---- Gate policy (Rule 2: config, not hardcoded logic) ---------------

    def get_gate_policy(self, *, project_id: str) -> GatePolicy:
        row = self._conn.execute(
            """
            SELECT block_on_any_contradiction,
                   flag_if_unverifiable_count_exceeds,
                   phase7_enabled
            FROM project_gate_policies WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            return GatePolicy()
        return GatePolicy(
            block_on_any_contradiction=bool(row["block_on_any_contradiction"]),
            flag_if_unverifiable_count_exceeds=int(
                row["flag_if_unverifiable_count_exceeds"]
            ),
            phase7_enabled=bool(row["phase7_enabled"]),
        )

    def set_gate_policy(
        self, *, project_id: str, policy: GatePolicy
    ) -> GatePolicy:
        # Validate project exists.
        self.get_project(project_id)
        now = _now()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO project_gate_policies
                    (project_id, block_on_any_contradiction,
                     flag_if_unverifiable_count_exceeds,
                     phase7_enabled, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    block_on_any_contradiction = excluded.block_on_any_contradiction,
                    flag_if_unverifiable_count_exceeds = excluded.flag_if_unverifiable_count_exceeds,
                    phase7_enabled = excluded.phase7_enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    1 if policy.block_on_any_contradiction else 0,
                    int(policy.flag_if_unverifiable_count_exceeds),
                    1 if policy.phase7_enabled else 0,
                    now.isoformat(),
                ),
            )
        return policy


def _run_from_row(row: sqlite3.Row) -> VerificationRun:
    versions = json.loads(row["source_document_versions_json"])
    verdicts_raw = json.loads(row["verdicts_json"])
    return VerificationRun(
        id=row["id"],
        project_id=row["project_id"],
        question=row["question"],
        model_or_prompt_label=row["model_or_prompt_label"],
        candidate_answer=row["candidate_answer"],
        source_document_versions={k: int(v) for k, v in versions.items()},
        verdicts=[_verdict_from_dict(d) for d in verdicts_raw],
        gate_result=row["gate_result"],
        latency_ms=float(row["latency_ms"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        phase7_retry_stop_reason=row["phase7_retry_stop_reason"],
        phase7_retry_attempts=int(row["phase7_retry_attempts"]),
        phase7_memory_item_ids=list(json.loads(row["phase7_memory_item_ids"])),
    )


# ---------- Gate policy per project (Rule 2) -------------------------------


_DEFAULT_GATE_POLICY = GatePolicy()


__all__ = [
    "StudioStore",
    "Project",
    "SourceDocument",
    "VerificationRun",
]
