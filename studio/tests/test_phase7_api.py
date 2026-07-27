"""Integration tests for the Phase 7 wiring of /checks.

Uses FastAPI TestClient + a real StudioStore on a tmp SQLite + the
real Soteria runtime + the real per-project Lethe SQLite. Source
documents contain a clean fact; the candidate answer is designed to
trigger either 'blocked' (a contradiction) or 'allowed' (only
entailed verdicts).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studio.api.app import create_app
from studio.db.store import StudioStore


# ---------- Helpers ---------------------------------------------------------


class _AlwaysContradictNli:
    """NLI stub that returns contradicted for every claim."""

    def score(self, claim, evidence):
        import numpy as np
        if not evidence:
            return np.zeros((0, 3), dtype=np.float32)
        return np.array([[0.85, 0.05, 0.10]] * len(evidence), dtype=np.float32)

    def verify(self, claim, evidence, checked_at=None):
        from datetime import datetime, timezone
        from elenchus.types import Evidence, Verdict
        checked = checked_at or datetime.now(timezone.utc)
        if not evidence:
            return Verdict(
                claim=claim, label="unverifiable", confidence=0.0,
                tier="nli", evidence=None, checked_at=checked,
            )
        return Verdict(
            claim=claim, label="contradicted", confidence=0.85,
            tier="nli", evidence=evidence[0], checked_at=checked,
        )


class _AlwaysEntailNli:
    """NLI stub that returns entailed for every claim."""

    def score(self, claim, evidence):
        import numpy as np
        if not evidence:
            return np.zeros((0, 3), dtype=np.float32)
        return np.array([[0.05, 0.90, 0.05]] * len(evidence), dtype=np.float32)

    def verify(self, claim, evidence, checked_at=None):
        from datetime import datetime, timezone
        from elenchus.types import Evidence, Verdict
        checked = checked_at or datetime.now(timezone.utc)
        if not evidence:
            return Verdict(
                claim=claim, label="unverifiable", confidence=0.0,
                tier="nli", evidence=None, checked_at=checked,
            )
        return Verdict(
            claim=claim, label="supported", confidence=0.90,
            tier="nli", evidence=evidence[0], checked_at=checked,
        )


def _client(tmp_path: Path, nli) -> TestClient:
    db_path = tmp_path / "studio.sqlite"
    store = StudioStore(db_path)
    app = create_app(store=store, nli_factory=lambda _cfg: nli)
    return TestClient(app)


def _create_project_with_source(client: TestClient, content: str) -> str:
    r = client.post("/api/projects", json={"name": "p"})
    project_id = r.json()["id"]
    client.post(
        f"/api/projects/{project_id}/source-documents",
        json={"name": "kb", "content": content},
    )
    return project_id


# ---------- Tests -----------------------------------------------------------


def test_phase7_disabled_by_default_no_retry_no_memory(tmp_path: Path) -> None:
    client = _client(tmp_path, _AlwaysContradictNli())
    pid = _create_project_with_source(client, "The sky is blue.")
    resp = client.post(
        f"/api/projects/{pid}/checks",
        json={
            "question": None,
            "model_or_prompt_label": "m",
            "candidate_answer": "The sky is green.",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["gate_result"] == "blocked"
    assert body["phase7_retry_stop_reason"] is None
    assert body["phase7_retry_attempts"] == 0
    assert body["phase7_memory_item_ids"] == []


def test_phase7_blocked_triggers_soteria_retry(tmp_path: Path) -> None:
    client = _client(tmp_path, _AlwaysContradictNli())
    pid = _create_project_with_source(client, "The sky is blue.")
    # Enable Phase 7 on this project.
    r = client.put(
        f"/api/projects/{pid}/gate-policy",
        json={
            "block_on_any_contradiction": True,
            "flag_if_unverifiable_count_exceeds": 1,
            "phase7_enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    resp = client.post(
        f"/api/projects/{pid}/checks",
        json={
            "question": None,
            "model_or_prompt_label": "m",
            "candidate_answer": "The sky is green.",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["gate_result"] == "blocked"
    assert body["phase7_retry_attempts"] >= 1
    assert body["phase7_retry_stop_reason"] in {
        "repeated_action", "max_steps", "max_runtime", "completed",
    }
    # Subsequent GET returns the persisted state.
    g = client.get(f"/api/runs/{body['id']}")
    assert g.json()["phase7_retry_attempts"] == body["phase7_retry_attempts"]


def test_phase7_allowed_writes_to_lethe(tmp_path: Path) -> None:
    client = _client(tmp_path, _AlwaysEntailNli())
    pid = _create_project_with_source(client, "The sky is blue.")
    client.put(
        f"/api/projects/{pid}/gate-policy",
        json={
            "block_on_any_contradiction": True,
            "flag_if_unverifiable_count_exceeds": 1,
            "phase7_enabled": True,
        },
    )
    resp = client.post(
        f"/api/projects/{pid}/checks",
        json={
            "question": None,
            "model_or_prompt_label": "m",
            "candidate_answer": "The sky is blue.",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["gate_result"] == "allowed"
    assert len(body["phase7_memory_item_ids"]) >= 1
    # Per-project Lethe SQLite exists at <tmp>/phase7/{pid}.sqlite.
    db_file = tmp_path / "phase7" / f"{pid}.sqlite"
    assert db_file.exists()


def test_phase7_missing_dep_returns_503(tmp_path: Path, monkeypatch) -> None:
    """Simulate a missing dep by patching the adapter proxy to raise."""
    from studio import integrations as integ

    def _explode(*args, **kwargs):
        raise integ.Phase7DependencyError("simulated missing soteria")

    monkeypatch.setattr(integ, "run_retry", _explode)
    db_path = tmp_path / "studio.sqlite"
    store = StudioStore(db_path)
    app = create_app(store=store, nli_factory=lambda _cfg: _AlwaysContradictNli())
    client = TestClient(app)
    pid = _create_project_with_source(client, "Sky is blue.")
    client.put(
        f"/api/projects/{pid}/gate-policy",
        json={
            "block_on_any_contradiction": True,
            "flag_if_unverifiable_count_exceeds": 1,
            "phase7_enabled": True,
        },
    )
    resp = client.post(
        f"/api/projects/{pid}/checks",
        json={
            "question": None,
            "model_or_prompt_label": "m",
            "candidate_answer": "Sky is green.",
        },
    )
    assert resp.status_code == 503
    assert "soteria-loop" in resp.json()["detail"]
