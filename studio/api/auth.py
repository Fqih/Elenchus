"""Auth middleware — bearer-token enforcement + simple in-process rate limiter.

Configuration via env:
    ELENCHUS_API_TOKEN         — single token (preferred for dev)
    ELENCHUS_API_TOKENS        — comma-separated list (preferred for multi-client)
    ELENCHUS_RATE_LIMIT_RPM    — per-token requests-per-minute default (default 600)

Security posture:
- When no tokens are configured, auth is **disabled** and everything is open.
  This matches local-dev expectations; production deployments MUST set
  ELENCHUS_API_TOKEN (or ELENCHUS_API_TOKENS).
- /health and /metrics are always open (consumed by load balancers and
  Prometheus scrapers).
- Auth runs as a Starlette middleware so it covers every /api/* route
  without per-route boilerplate.
- Rate limit is a sliding window in deque(deque of timestamps) per
  token (or per-IP if anonymous). No Redis, no external deps.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Deque, Iterable, Optional


def _load_tokens() -> Optional[list[str]]:
    """Resolve the configured token set, or None to indicate auth is off."""
    multi = os.environ.get("ELENCHUS_API_TOKENS", "").strip()
    if multi:
        toks = [t.strip() for t in multi.split(",") if t.strip()]
        return toks or None
    single = os.environ.get("ELENCHUS_API_TOKEN", "").strip()
    if single:
        return [single]
    return None


def _rpm_default() -> int:
    raw = os.environ.get("ELENCHUS_RATE_LIMIT_RPM", "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 600


class _SlidingWindow:
    """Per-key sliding-window counter of recent request timestamps."""

    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._windows: dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        window = self._windows[key]
        # Drop entries older than 60 s.
        while window and (now - window[0]) > 60.0:
            window.popleft()
        if len(window) >= self._max:
            # Time until the oldest entry falls out of the 60s window.
            wait = max(1, int(60.0 - (now - window[0])))
            return False, wait
        window.append(now)
        return True, 0


def install_auth(
    app,
    *,
    tokens: Optional[Iterable[str]] = None,
    rate_limit_rpm: Optional[int] = None,
    open_paths: tuple[str, ...] = ("/health", "/metrics"),
) -> None:
    """Install bearer auth + rate limit middleware on the given FastAPI app.

    Args:
        app: FastAPI instance to instrument.
        tokens: explicitly-configured token set; if None, load from env.
            When None or empty, auth is disabled.
        rate_limit_rpm: requests-per-minute per token. None = load from env.
        open_paths: paths that bypass auth and rate limiting entirely.
            Defaults to /health and /metrics.
    """
    resolved_tokens: Optional[list[str]] = None
    if tokens is not None:
        resolved_tokens = list(tokens) or None
    if resolved_tokens is None:
        resolved_tokens = _load_tokens()

    if rate_limit_rpm is None:
        rate_limit_rpm = _rpm_default()

    limiter = _SlidingWindow(rate_limit_rpm) if rate_limit_rpm > 0 else None

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            # Always-open paths short-circuit.
            if path in open_paths:
                return await call_next(request)
            # Only /api/* is protected.
            if not path.startswith("/api/"):
                return await call_next(request)

            # Auth disabled (no tokens): allow but still rate-limit per IP.
            key = request.client.host if request.client else "unknown"
            if resolved_tokens:
                auth = request.headers.get("authorization", "")
                if not auth.lower().startswith("bearer "):
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "missing bearer token"},
                    )
                presented = auth[7:].strip()
                if presented not in resolved_tokens:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "invalid bearer token"},
                    )
                key = presented

            if limiter is not None:
                now = time.monotonic()
                allowed, retry_after = limiter.check(key, now)
                if not allowed:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "rate limit exceeded"},
                        headers={"Retry-After": str(retry_after)},
                    )

            return await call_next(request)

    app.add_middleware(AuthMiddleware)


__all__ = ["install_auth"]
