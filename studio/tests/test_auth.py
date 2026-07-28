"""Auth tests — covers /health open, /api requires token, multi-token, no token = 503 mode.

Studio tests can run WITHOUT real NLI (the auth/metrics surface is
independent of the model). We mount a trivial /api route in the same
FastAPI app under test to exercise the middleware.
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from studio.api.auth import install_auth


def _build_app(*, tokens: list[str] | None, rate_limit_rpm: int = 10000):
    """Construct a FastAPI app with /health, /api/echo, plus auth middleware."""
    app = FastAPI()
    install_auth(app, tokens=tokens, rate_limit_rpm=rate_limit_rpm)

    @app.get("/health")
    def health():
        return {"ok": True}

    api = app.router if False else _register_api(app)

    return app


def _register_api(app: FastAPI):
    from fastapi import APIRouter

    api = APIRouter(prefix="/api")

    @api.get("/echo")
    def echo():
        return {"hello": "world"}

    app.include_router(api)
    return api


@pytest.fixture
def env_clean(monkeypatch):
    for v in (
        "ELENCHUS_API_TOKEN",
        "ELENCHUS_API_TOKENS",
        "ELENCHUS_RATE_LIMIT_RPM",
    ):
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


def test_health_does_not_require_token(env_clean):
    env_clean.setenv("ELENCHUS_API_TOKEN", "secret123")
    app = _build_app(tokens=["secret123"])
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_api_without_token_when_configured_returns_401(env_clean):
    env_clean.setenv("ELENCHUS_API_TOKEN", "secret123")
    app = _build_app(tokens=["secret123"])
    r = TestClient(app).get("/api/echo")
    assert r.status_code == 401


def test_api_with_correct_token_returns_200(env_clean):
    env_clean.setenv("ELENCHUS_API_TOKEN", "secret123")
    app = _build_app(tokens=["secret123"])
    r = TestClient(app).get(
        "/api/echo", headers={"Authorization": "Bearer secret123"}
    )
    assert r.status_code == 200
    assert r.json() == {"hello": "world"}


def test_api_with_wrong_token_returns_401(env_clean):
    env_clean.setenv("ELENCHUS_API_TOKEN", "secret123")
    app = _build_app(tokens=["secret123"])
    r = TestClient(app).get(
        "/api/echo", headers={"Authorization": "Bearer wrong"}
    )
    assert r.status_code == 401


def test_no_tokens_configured_disables_auth_for_dev(env_clean):
    """When ELENCHUS_API_TOKEN is unset, /api/* is open. Useful for local dev.

    Per spec: in production you MUST set ELENCHUS_API_TOKEN. The middleware
    never fails closed unless at least one token is configured.
    """
    app = _build_app(tokens=None)
    r = TestClient(app).get("/api/echo")
    assert r.status_code == 200


def test_multiple_tokens_all_accepted(env_clean):
    env_clean.setenv("ELENCHUS_API_TOKENS", "tok1,tok2,tok3")
    app = _build_app(tokens=["tok1", "tok2", "tok3"])
    c = TestClient(app)
    for t in ("tok1", "tok2", "tok3"):
        r = c.get("/api/echo", headers={"Authorization": f"Bearer {t}"})
        assert r.status_code == 200, f"token {t} should work"


def test_rate_limit_returns_429_after_threshold(env_clean):
    """Hit /api/echo more than the limit and expect HTTP 429 on the overage."""
    env_clean.setenv("ELENCHUS_API_TOKEN", "t")
    app = _build_app(tokens=["t"], rate_limit_rpm=3)
    c = TestClient(app)
    headers = {"Authorization": "Bearer t"}
    assert c.get("/api/echo", headers=headers).status_code == 200
    assert c.get("/api/echo", headers=headers).status_code == 200
    assert c.get("/api/echo", headers=headers).status_code == 200
    # 4th request in the same window should be rate-limited.
    r = c.get("/api/echo", headers=headers)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_invalid_authorization_header_format_returns_401(env_clean):
    env_clean.setenv("ELENCHUS_API_TOKEN", "t")
    app = _build_app(tokens=["t"])
    c = TestClient(app)
    r = c.get("/api/echo", headers={"Authorization": "t"})
    assert r.status_code == 401
    r = c.get("/api/echo", headers={"Authorization": "Basic dDp0"})
    assert r.status_code == 401
