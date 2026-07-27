"""Integration tests for the Phase 7 recall endpoint.

GET /api/projects/{project_id}/runs/{run_id}/memory-claims -> MemoryClaim[]
The endpoint surfaces Lethe's per-project storage filtered by run_id.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from studio.api.app import create_app
from studio.db.store import StudioStore
from studio.integrations.lethe import write_supported_claims
from elenchus.types import Claim, Evidence, Verdict


def _verdict(text: str, label: str = "supported", source_id: str = "kb") -> Verdict:
    return Verdict(
        claim=Claim(id=f"c-{text[:4]}", text=text, span=(0, len(text))),
        label=label,  # type: ignore[arg-type]
        confidence=0.9,
        tier="nli",
        evidence=Evidence(source_id=source_id, text="E", span=(0, 1)),
        checked_at=datetime.now(timezone.utc),
    )


def _client(tmp_path) -> TestClient:
    db_path = tmp_path / "studio.sqlite"
    store = StudioStore(db_path)
    app = create_app(store=store)
    return TestClient(app), store, db_path


def _create_project_with_run(client: TestClient, store: StudioStore, verdict: Verdict) -> tuple[str, str]:
    r = client.post("/api/projects", json={"name": "p"})
    pid = r.json()["id"]
    # Insert a run directly into the store so we can GET it.
    run = store.record_run(
        project_id=pid, question=None, model_or_prompt_label="m",
        candidate_answer="answer", source_versions={verdict.evidence.source_id: 1},
        verdicts=[verdict], gate_result="allowed", latency_ms=1.0,
    )
    return pid, run.id


def test_recall_empty_when_run_has_no_memory_items(tmp_path) -> None:
    client, store, _ = _client(tmp_path)
    pid, run_id = _create_project_with_run(client, store, _verdict("none"))
    r = client.get(f"/api/projects/{pid}/runs/{run_id}/memory-claims")
    assert r.status_code == 200
    assert r.json() == []


def test_recall_returns_memory_items_for_run(tmp_path) -> None:
    client, store, db_path = _client(tmp_path)
    pid, run_id = _create_project_with_run(
        client, store,
        _verdict("We accept returns within 30 days."),
    )
    # Write a couple of supported claims directly via the adapter.
    write_supported_claims(
        project_id=pid,
        run_id=run_id,
        verdicts=[
            _verdict("We accept returns within 30 days."),
            _verdict("Refunds arrive within 5 business days."),
        ],
        source_versions={"kb": 1},
        db_dir=db_path.parent,
    )
    r = client.get(f"/api/projects/{pid}/runs/{run_id}/memory-claims")
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    first = items[0]
    # All Lethe-side fields the UI needs.
    for key in (
        "id", "content", "tags", "source_session_id",
        "created_at", "last_accessed_at",
        "access_count", "importance_score",
    ):
        assert key in first, f"missing {key}"
    # No embedding in the wire format — it's not UI-relevant.
    assert "embedding" not in first


def test_recall_filters_by_run_id(tmp_path) -> None:
    """A run's memory-claims must not include items from a different run."""
    client, store, db_path = _client(tmp_path)
    pid, _first_run_id = _create_project_with_run(client, store, _verdict("a"))
    # Two more runs — both real IDs in the studio store.
    run_a = store.record_run(
        project_id=pid, question=None, model_or_prompt_label="m",
        candidate_answer="a", source_versions={"kb": 1},
        verdicts=[_verdict("aaa")], gate_result="allowed", latency_ms=1.0,
    )
    run_b = store.record_run(
        project_id=pid, question=None, model_or_prompt_label="m",
        candidate_answer="b", source_versions={"kb": 1},
        verdicts=[_verdict("bbb")], gate_result="allowed", latency_ms=1.0,
    )
    write_supported_claims(
        project_id=pid, run_id=run_a.id,
        verdicts=[_verdict("AAA")], source_versions={"kb": 1},
        db_dir=db_path.parent,
    )
    write_supported_claims(
        project_id=pid, run_id=run_b.id,
        verdicts=[_verdict("BBB")], source_versions={"kb": 1},
        db_dir=db_path.parent,
    )
    a = client.get(f"/api/projects/{pid}/runs/{run_a.id}/memory-claims")
    b = client.get(f"/api/projects/{pid}/runs/{run_b.id}/memory-claims")
    # Run id that exists in the studio but has no Lethe items.
    empty = client.get(f"/api/projects/{pid}/runs/{_first_run_id}/memory-claims")
    assert a.status_code == 200 and len(a.json()) == 1
    assert b.status_code == 200 and len(b.json()) == 1
    assert empty.status_code == 200 and empty.json() == []
    assert a.json()[0]["content"] == "AAA"
    assert b.json()[0]["content"] == "BBB"


def test_recall_unknown_project_returns_404(tmp_path) -> None:
    client, store, _ = _client(tmp_path)
    _create_project_with_run(client, store, _verdict("x"))
    r = client.get("/api/projects/does-not-exist/runs/run-A/memory-claims")
    assert r.status_code == 404


def test_recall_unknown_run_returns_404(tmp_path) -> None:
    client, store, _ = _client(tmp_path)
    pid, _ = _create_project_with_run(client, store, _verdict("x"))
    r = client.get(f"/api/projects/{pid}/runs/no-such-run/memory-claims")
    assert r.status_code == 404


def test_recall_excludes_contradicted_verdicts(tmp_path) -> None:
    """Only supported verdicts are written to Lethe; the recall reflects that."""
    client, store, db_path = _client(tmp_path)
    pid, run_id = _create_project_with_run(client, store, _verdict("a"))
    write_supported_claims(
        project_id=pid, run_id=run_id,
        verdicts=[
            _verdict("good", label="supported"),
            _verdict("bad", label="contradicted"),
            _verdict("meh", label="unverifiable"),
        ],
        source_versions={"kb": 1},
        db_dir=db_path.parent,
    )
    r = client.get(f"/api/projects/{pid}/runs/{run_id}/memory-claims")
    assert r.status_code == 200
    contents = [item["content"] for item in r.json()]
    assert "good" in contents
    assert "bad" not in contents
    assert "meh" not in contents
