"""Schema tests for the Phase 7 columns on gate policy and runs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from elenchus.types import Claim, Evidence, Verdict

from studio.db.store import StudioStore
from studio.gate import GatePolicy


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tmp_store(tmp_path: Path) -> StudioStore:
    return StudioStore(tmp_path / "studio.sqlite")


def _verdict(label: str = "entailed") -> Verdict:
    return Verdict(
        claim=Claim(id="c1", text="C", span=(0, 1)),
        label=label,  # type: ignore[arg-type]
        confidence=0.9,
        tier="nli",
        evidence=Evidence(source_id="s1", text="E", span=(0, 1)),
        checked_at=_now(),
    )


def test_gate_policy_default_phase7_disabled(tmp_path: Path) -> None:
    store = _tmp_store(tmp_path)
    p = store.create_project(name="x")
    policy = store.get_gate_policy(project_id=p.id)
    assert policy.phase7_enabled is False


def test_gate_policy_round_trips_phase7_enabled(tmp_path: Path) -> None:
    store = _tmp_store(tmp_path)
    p = store.create_project(name="x")
    store.set_gate_policy(
        project_id=p.id,
        policy=GatePolicy(phase7_enabled=True),
    )
    fetched = store.get_gate_policy(project_id=p.id)
    assert fetched.phase7_enabled is True


def test_record_run_round_trips_phase7_fields(tmp_path: Path) -> None:
    store = _tmp_store(tmp_path)
    p = store.create_project(name="x")
    run = store.record_run(
        project_id=p.id, question=None, model_or_prompt_label="m",
        candidate_answer="A", source_versions={"s1": 1}, verdicts=[_verdict()],
        gate_result="blocked", latency_ms=12.0,
        phase7_retry_stop_reason="repeated_action",
        phase7_retry_attempts=2,
        phase7_memory_item_ids=["mem-1", "mem-2"],
    )
    fetched = store.get_run(run_id=run.id)
    assert fetched.phase7_retry_stop_reason == "repeated_action"
    assert fetched.phase7_retry_attempts == 2
    assert fetched.phase7_memory_item_ids == ["mem-1", "mem-2"]


def test_record_run_defaults_phase7_fields_when_omitted(tmp_path: Path) -> None:
    store = _tmp_store(tmp_path)
    p = store.create_project(name="x")
    run = store.record_run(
        project_id=p.id, question=None, model_or_prompt_label="m",
        candidate_answer="A", source_versions={}, verdicts=[],
        gate_result="allowed", latency_ms=1.0,
    )
    fetched = store.get_run(run_id=run.id)
    assert fetched.phase7_retry_stop_reason is None
    assert fetched.phase7_retry_attempts == 0
    assert fetched.phase7_memory_item_ids == []


def test_migration_is_idempotent(tmp_path: Path) -> None:
    """Re-opening an existing Phase 5 DB with Phase 7 migration must not raise."""
    db_path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE verification_runs (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, question TEXT,
            model_or_prompt_label TEXT NOT NULL, candidate_answer TEXT NOT NULL,
            source_document_versions_json TEXT NOT NULL, verdicts_json TEXT NOT NULL,
            gate_result TEXT NOT NULL, latency_ms REAL NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE project_gate_policies (
            project_id TEXT PRIMARY KEY,
            block_on_any_contradiction INTEGER NOT NULL,
            flag_if_unverifiable_count_exceeds INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()
    # Opening via StudioStore must apply the Phase 7 migration cleanly.
    store = StudioStore(db_path)
    # And opening again is a no-op.
    store.close()
    store = StudioStore(db_path)
    assert store.get_gate_policy is not None  # smoke