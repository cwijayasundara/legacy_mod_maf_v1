"""Tests for the FastAPI orchestrator endpoints (orchestrator/api.py)."""

import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add orchestrator directory to sys.path so bare imports (used by api.py) resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness", "orchestrator"))

# Import the api module directly (orchestrator/ has no __init__.py; its files
# use bare imports like "from ado_client import AdoClient")
import api as api_mod  # noqa: E402


def _make_test_app(tmp_project):
    """
    Return a configured FastAPI app with mocked global state so that
    the /health and /migrate endpoints work without the lifespan init.
    """
    from fastapi.testclient import TestClient

    # Wire up lightweight fakes for the three global clients
    sm = MagicMock()
    sm.is_connected.return_value = False

    ado = MagicMock()
    ado.is_configured.return_value = False

    runner = MagicMock()
    runner.is_available.return_value = True
    # run() is async in production; make it an AsyncMock that never calls Codex
    runner.run = AsyncMock(return_value=(True, "mocked output"))

    # Inject into the module-level globals that the endpoints read
    api_mod.state_manager = sm
    api_mod.ado_client = ado
    api_mod.codex_runner = runner
    api_mod.PROJECT_ROOT = str(tmp_project)

    return TestClient(api_mod.app, raise_server_exceptions=False)


# ---------- tests ----------


def test_health(tmp_project):
    client = _make_test_app(tmp_project)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


def test_migrate_missing_module(tmp_project):
    """POST /migrate with a module that does not exist should return 404."""
    client = _make_test_app(tmp_project)
    resp = client.post(
        "/migrate",
        json={"module": "nonexistent-module", "language": "python"},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_migrate_invalid_language(tmp_project):
    """POST /migrate with an unsupported language should return 400."""
    client = _make_test_app(tmp_project)
    resp = client.post(
        "/migrate",
        json={"module": "order-processor", "language": "rust"},
    )
    assert resp.status_code == 400
    assert "Invalid language" in resp.json()["detail"]


def test_migrate_validation(tmp_project):
    """POST /migrate with a valid request should return 200 with status accepted."""
    client = _make_test_app(tmp_project)
    resp = client.post(
        "/migrate",
        json={"module": "order-processor", "language": "python"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["module"] == "order-processor"
