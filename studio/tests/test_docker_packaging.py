"""Tests for the Docker packaging artifacts (Phase 15).

These tests don't build or run the image — that would require Docker
daemon + a working Python build. We verify the artifacts as plain
files: the Dockerfile has the right stage names, the compose file
parses with the Python yaml library, and `.dockerignore` blocks the
correct paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_backend_exists():
    assert (REPO_ROOT / "Dockerfile.backend").is_file()


def test_dockerfile_has_required_stages():
    text = (REPO_ROOT / "Dockerfile.backend").read_text()
    assert "FROM python:3.11-slim" in text
    assert "FROM node:20-slim" in text
    assert "AS frontend-build" in text
    assert "AS runtime" in text


def test_dockerfile_installs_required_extras():
    text = (REPO_ROOT / "Dockerfile.backend").read_text()
    assert "pip install -e" in text
    assert "[dev,studio,eval" in text


def test_dockerfile_health_check_uses_health_endpoint():
    text = (REPO_ROOT / "Dockerfile.backend").read_text()
    assert "HEALTHCHECK" in text
    assert "/health" in text


def test_dockerfile_cmd_targets_the_real_server():
    text = (REPO_ROOT / "Dockerfile.backend").read_text()
    assert "studio.api.server" in text


def test_compose_file_parses_and_has_required_keys():
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    parsed = yaml.safe_load(text)
    assert parsed["name"] == "elenchus"
    assert "app" in parsed["services"]
    app = parsed["services"]["app"]
    assert "build" in app
    assert app["build"]["dockerfile"] == "Dockerfile.backend"
    assert "elenchus-data" in parsed["volumes"]


def test_compose_runs_with_bearer_token_overridable_via_env():
    parsed = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    env = parsed["services"]["app"]["environment"]
    # Token is allowed to be empty (dev) but must be defined.
    assert "ELENCHUS_API_TOKEN" in env
    # Rate limit default — Docker's `${VAR:-600}` interpolation syntax.
    # Strip the wrapper and confirm the default is sane.
    rpm_raw = env["ELENCHUS_RATE_LIMIT_RPM"]
    assert isinstance(rpm_raw, str)
    # Forms: "600" (literal) or "${ELENCHUS_RATE_LIMIT_RPM:-600}" (default).
    if rpm_raw.startswith("${"):
        default_part = rpm_raw.split(":-", 1)[1].rstrip("}")
        assert int(default_part) > 0
    else:
        assert int(rpm_raw) > 0


def test_dockerignore_excludes_node_modules_and_pyc():
    text = (REPO_ROOT / ".dockerignore").read_text()
    assert "studio/frontend/node_modules" in text
    assert "__pycache__" in text
    assert "*.sqlite" in text
