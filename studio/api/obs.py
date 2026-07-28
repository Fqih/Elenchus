"""Observability primitives — Prometheus-format metrics + JSON-structured logging.

No external deps. stdlib `logging` is enough for structured records
(format with JSON formatter). Metrics follow the Prometheus text exposition
format (https://prometheus.io/docs/instrumenting/exposition_formats/) so
they work with any compatible scraper.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import defaultdict
from typing import Iterable, Optional

# Default histogram bucket boundaries in milliseconds.
DEFAULT_LATENCY_BUCKETS: tuple[float, ...] = (
    5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0,
    1000.0, 2500.0, 5000.0, 10000.0,
)


class Counter:
    """Labelled counter — sum of `inc()` calls per label tuple."""

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help = help_text
        self._values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, labels: Optional[dict[str, str]] = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            self._values[key] += amount

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}",
                 f"# TYPE {self.name} counter"]
        with self._lock:
            items = list(self._values.items())
        for key, value in sorted(items):
            label_str = _label_str(key)
            lines.append(f"{self.name}{label_str} {_format_number(value)}")
        return "\n".join(lines)


class Histogram:
    """Labelled histogram with fixed bucket boundaries + count/sum."""

    def __init__(
        self,
        name: str,
        help_text: str,
        buckets: tuple[float, ...] = DEFAULT_LATENCY_BUCKETS,
    ) -> None:
        self.name = name
        self.help = help_text
        self._buckets = tuple(sorted(set(buckets)))
        self._counts: dict[tuple[tuple[str, str], ...], list[int]] = defaultdict(
            lambda: [0] * (len(self._buckets) + 1)  # +1 for +Inf bucket
        )
        self._sums: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._totals: dict[tuple[tuple[str, str], ...], int] = defaultdict(int)
        self._lock = threading.Lock()

    def observe(self, value: float, labels: Optional[dict[str, str]] = None) -> None:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            bucket_idx = self._bucket_index(value)
            self._counts[key][bucket_idx] += 1
            self._sums[key] += value
            self._totals[key] += 1

    def _bucket_index(self, value: float) -> int:
        for i, boundary in enumerate(self._buckets):
            if value <= boundary:
                return i
        return len(self._buckets)  # +Inf

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}",
                 f"# TYPE {self.name} histogram"]
        with self._lock:
            keys = sorted(set(self._counts) | set(self._sums))
            for key in keys:
                label_str = _label_str(key)
                counts = self._counts.get(key, [0] * (len(self._buckets) + 1))
                running = 0
                bucket_lines = []
                for i, boundary in enumerate(self._buckets):
                    running += counts[i]
                    bucket_label = _extend_label_str(label_str, {"le": _format_number(boundary)})
                    bucket_lines.append(
                        f"{self.name}_bucket{bucket_label} {running}"
                    )
                running += counts[-1]  # +Inf
                inf_label = _extend_label_str(label_str, {"le": "+Inf"})
                bucket_lines.append(f"{self.name}_bucket{inf_label} {running}")
                lines.extend(bucket_lines)
                total = self._totals.get(key, 0)
                total_sum = self._sums.get(key, 0.0)
                lines.append(f"{self.name}_count{label_str} {total}")
                lines.append(f"{self.name}_sum{label_str} {_format_number(total_sum)}")
        return "\n".join(lines)


class MetricsRegistry:
    """Container for all Elenchus metrics. Single instance per process."""

    def __init__(self) -> None:
        # Counters.
        self.checks_total = Counter(
            "elenchus_checks_total",
            "Total verification runs submitted, by gate_result label.",
        )
        self.gate_decisions_total = Counter(
            "elenchus_gate_decisions_total",
            "Total gate decisions, by outcome (allowed/blocked/flagged).",
        )
        self.phase7_retry_attempts_total = Counter(
            "elenchus_phase7_retry_attempts_total",
            "Total Soteria retry attempts across Phase 7 runs.",
        )
        self.phase7_memory_writes_total = Counter(
            "elenchus_phase7_memory_writes_total",
            "Total Lethe MemoryItems stored across Phase 7 runs.",
        )
        self.http_requests_total = Counter(
            "elenchus_http_requests_total",
            "HTTP requests served, by path + status label.",
        )
        # Histograms.
        self.check_latency_ms = Histogram(
            "elenchus_check_latency_ms",
            "End-to-end verification latency in milliseconds.",
        )
        self.http_request_latency_ms = Histogram(
            "elenchus_http_request_latency_ms",
            "HTTP request latency in milliseconds.",
        )

    def inc(self, name: str, *, amount: float = 1.0, labels: Optional[dict[str, str]] = None) -> None:
        # `name` may be either the metric name ("elenchus_checks_total") or
        # the attribute name ("checks_total"). Walk the registry.
        attr_name = name.split("elenchus_")[-1] if name.startswith("elenchus_") else name
        if hasattr(self, attr_name):
            obj = getattr(self, attr_name)
            if isinstance(obj, Counter):
                obj.inc(amount=amount, labels=labels)

    def histogram(self, name: str) -> Histogram:
        attr_name = name.split("elenchus_")[-1] if name.startswith("elenchus_") else name
        if hasattr(self, attr_name):
            obj = getattr(self, attr_name)
            if isinstance(obj, Histogram):
                return obj
        raise AttributeError(f"unknown histogram {name!r}")

    def render(self) -> str:
        counters = [
            self.checks_total,
            self.gate_decisions_total,
            self.phase7_retry_attempts_total,
            self.phase7_memory_writes_total,
            self.http_requests_total,
        ]
        histograms = [self.check_latency_ms, self.http_request_latency_ms]
        return "\n".join(c.render() for c in counters + histograms)


def _label_str(label_pairs: tuple[tuple[str, str], ...]) -> str:
    if not label_pairs:
        return ""
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in label_pairs) + "}"


def _extend_label_str(existing: str, extra: dict[str, str]) -> str:
    extra_pairs = ",".join(f'{k}="{_escape(v)}"' for k, v in extra.items())
    if not existing:
        return "{" + extra_pairs + "}"
    if existing.endswith("}"):
        body = existing[1:-1]
        return "{" + body + "," + extra_pairs + "}"
    return "{" + extra_pairs + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_number(n: float) -> str:
    if isinstance(n, int):
        return str(n)
    if math.isnan(n):
        return "NaN"
    if math.isinf(n):
        return "+Inf" if n > 0 else "-Inf"
    return f"{n:.6f}"


# ---------- JSON logging ------------------------------------------------


class _JsonFormatter(logging.Formatter):
    """Render each LogRecord as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": time.time(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Attach any extra=... attributes that aren't standard LogRecord fields.
        std_fields = set(logging.LogRecord(
            "", 0, "", 0, "", (), None
        ).__dict__.keys()) | {"message", "asctime"}
        for k, v in record.__dict__.items():
            if k not in std_fields and not k.startswith("_"):
                payload[k] = v
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_json_logging(
    *,
    level: int = logging.INFO,
    extra_handlers: Optional[Iterable[logging.Handler]] = None,
    logger_name: str = "elenchus",
) -> None:
    """Install a JSON formatter on the `elenchus` logger.

    All log records will emit one line of JSON. The middleware in
    studio.api.app uses `logger.info("check_complete", extra=...)` to
    attach structured fields.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    log = logging.getLogger(logger_name)
    log.handlers.clear()
    log.addHandler(handler)
    for h in extra_handlers or ():
        log.addHandler(h)
    log.setLevel(level)
    log.propagate = False


# ---------- /metrics endpoint -------------------------------------------


def install_metrics_endpoint(app, registry: MetricsRegistry) -> None:
    """Mount a /metrics route that returns Prometheus text format."""
    from fastapi import Response

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(
            content=registry.render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )


__all__ = [
    "Counter",
    "Histogram",
    "MetricsRegistry",
    "install_metrics_endpoint",
    "configure_json_logging",
]
