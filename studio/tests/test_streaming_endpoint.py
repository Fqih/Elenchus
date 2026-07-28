"""Phase 13: streaming check endpoint (Server-Sent Events).

`POST /api/projects/{project_id}/checks/stream` emits per-claim verdicts
as SSE events. The endpoint must:
  - yield one `event: claim` per verdict
  - end with `event: summary` containing the persisted run
  - persist the run (so subsequent GET /runs/{id} still works)
  - return 404 if the project doesn't exist
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from studio.api.app import create_app
from studio.api.obs import MetricsRegistry
from studio.db.store import StudioStore


def _parse_sse(raw: str):
    """Yield `(event, data_dict)` tuples from an SSE response body."""
    event = None
    data_lines: list[str] = []
    for line in raw.splitlines():
        if not line:
            if event is not None and data_lines:
                payload = "\n".join(data_lines)
                try:
                    yield event, json.loads(payload)
                except json.JSONDecodeError:
                    yield event, {"raw": payload}
            event = None
            data_lines = []
            continue
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())


def _read_stream(resp) -> str:
    """Drain a streaming response into a single string."""
    chunks = []
    for chunk in resp.iter_bytes():
        chunks.append(chunk.decode("utf-8"))
    return "".join(chunks)


@pytest.fixture
def app():
    store = StudioStore(":memory:")
    client = TestClient(create_app(store=store, metrics=MetricsRegistry()))
    yield client
    store.close()


def test_streaming_endpoint_returns_sse_per_claim(app):
    """Each verdict is its own SSE event, summary event closes the stream."""
    proj = app.post("/api/projects", json={"name": "Phase13"}).json()
    app.post(
        f"/api/projects/{proj['id']}/source-documents",
        json={"name": "kb", "content": "Standard shipping takes 3 to 5 days."},
    )

    with app.stream(
        "POST",
        f"/api/projects/{proj['id']}/checks/stream",
        json={
            "question": "How long is shipping?",
            "candidate_answer": "Standard shipping takes 3 to 5 days. Returns within 30 days.",
            "model_or_prompt_label": "test-model",
        },
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        raw = _read_stream(resp)

    events = list(_parse_sse(raw))
    claim_events = [e for e in events if e[0] == "claim"]
    summary_events = [e for e in events if e[0] == "summary"]

    assert len(claim_events) >= 1, f"expected at least 1 claim event, got {events}"
    assert len(summary_events) == 1, f"expected exactly 1 summary event, got {events}"

    summary = summary_events[0][1]["data"]
    assert summary["project_id"] == proj["id"]
    assert summary["model_or_prompt_label"] == "test-model"
    assert summary["gate_result"] in {"allowed", "blocked", "flagged"}


def test_streaming_endpoint_persists_the_run(app):
    """The summary event must include a real run_id that GET /runs returns."""
    proj = app.post("/api/projects", json={"name": "Phase13 persist"}).json()
    app.post(
        f"/api/projects/{proj['id']}/source-documents",
        json={"name": "kb", "content": "Returns within 30 days."},
    )

    with app.stream(
        "POST",
        f"/api/projects/{proj['id']}/checks/stream",
        json={
            "question": "policy?",
            "candidate_answer": "Returns within 30 days.",
            "model_or_prompt_label": "persist-test",
        },
    ) as resp:
        raw = _read_stream(resp)

    events = list(_parse_sse(raw))
    summary = next(d for e, d in events if e == "summary")
    run_id = summary["data"]["id"]

    # Confirm the persisted run is retrievable via the existing GET endpoint.
    got = app.get(f"/api/runs/{run_id}")
    assert got.status_code == 200
    assert got.json()["model_or_prompt_label"] == "persist-test"


def test_streaming_endpoint_404_for_unknown_project(app):
    """Unknown project_id → 404, not a stream."""
    resp = app.post(
        "/api/projects/nonexistent/checks/stream",
        json={
            "question": "?",
            "candidate_answer": "?",
            "model_or_prompt_label": "x",
        },
    )
    assert resp.status_code == 404


def test_streaming_endpoint_claim_event_shape(app):
    """Each claim event has claim / label / tier / confidence keys."""
    proj = app.post("/api/projects", json={"name": "Phase13 shape"}).json()
    app.post(
        f"/api/projects/{proj['id']}/source-documents",
        json={"name": "kb", "content": "Returns within 30 days."},
    )

    with app.stream(
        "POST",
        f"/api/projects/{proj['id']}/checks/stream",
        json={
            "question": "?",
            "candidate_answer": "Returns within 30 days.",
            "model_or_prompt_label": "shape-test",
        },
    ) as resp:
        raw = _read_stream(resp)

    events = list(_parse_sse(raw))
    claim_event = next(d for e, d in events if e == "claim")
    payload = claim_event["data"]
    for key in ("claim", "label", "tier", "confidence"):
        assert key in payload, f"missing key {key} in {payload}"
    assert "text" in payload["claim"]
