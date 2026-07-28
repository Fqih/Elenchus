"""Observability tests — covers /metrics endpoint and structured logging."""

from __future__ import annotations

import io
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio.api.obs import (
    MetricsRegistry,
    _JsonFormatter,
    configure_json_logging,
    install_metrics_endpoint,
)


@pytest.fixture
def app_with_metrics():
    app = FastAPI()
    registry = MetricsRegistry()
    install_metrics_endpoint(app, registry)
    return app, registry


def test_metrics_endpoint_returns_prometheus_text(app_with_metrics):
    app, _ = app_with_metrics
    r = TestClient(app).get("/metrics")
    assert r.status_code == 200
    # Prometheus exposition format: lines like "# HELP ..." and "name value".
    assert "# HELP" in r.text or "# TYPE" in r.text


def test_counter_increments_and_appears_in_metrics(app_with_metrics):
    app, registry = app_with_metrics
    registry.inc("elenchus_checks_total", labels={"gate": "blocked"})
    registry.inc("elenchus_checks_total", labels={"gate": "blocked"})
    registry.inc("elenchus_checks_total", labels={"gate": "allowed"})
    body = TestClient(app).get("/metrics").text
    assert 'elenchus_checks_total{gate="blocked"} 2' in body
    assert 'elenchus_checks_total{gate="allowed"} 1' in body


def test_histogram_emits_bucket_and_count_lines(app_with_metrics):
    app, registry = app_with_metrics
    h = registry.histogram("elenchus_check_latency_ms")
    for ms in (10, 50, 100, 200, 500, 1000, 2000):
        h.observe(float(ms))
    body = TestClient(app).get("/metrics").text
    # Prometheus histogram format: cumulative bucket counts with `le=` label.
    assert "elenchus_check_latency_ms_bucket" in body
    assert 'elenchus_check_latency_ms_bucket{le="5.000000"} 0' in body
    assert 'elenchus_check_latency_ms_bucket{le="+Inf"} 7' in body
    assert "elenchus_check_latency_ms_count 7" in body
    # Sum reports total observed milliseconds.
    assert "elenchus_check_latency_ms_sum" in body


def test_json_logging_emits_structured_records():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_JsonFormatter())
    configure_json_logging(
        level=logging.INFO,
        extra_handlers=[handler],
        logger_name="elenchus.test",
    )

    log = logging.getLogger("elenchus.test")
    log.info("hello", extra={"project_id": "p1", "claim_count": 3})

    output = stream.getvalue().strip()
    # Must be valid JSON.
    import json

    record = json.loads(output)
    assert record["msg"] == "hello"
    assert record["project_id"] == "p1"
    assert record["claim_count"] == 3
    assert record["level"] == "info"


def test_metrics_endpoint_does_not_require_auth():
    """/metrics is intentionally open like /health for Prometheus scrapers."""
    app = FastAPI()
    install_metrics_endpoint(app, MetricsRegistry())
    r = TestClient(app).get("/metrics")
    assert r.status_code == 200
