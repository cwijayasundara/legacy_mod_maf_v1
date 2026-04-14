from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from agent_harness.orchestrator import api as api_mod
    api_mod._pipeline = None
    api_mod._ado = None
    from agent_harness.persistence.repository import MigrationRepository
    api_mod._discovery_repo = MigrationRepository(db_path=tmp_path / "disc.db")
    api_mod._discovery_repo.initialize()
    return TestClient(api_mod.app)


def test_discover_surfaces_token_budget_exceeded_as_402(client, tmp_path):
    repo_root = tmp_path / "synth"
    repo_root.mkdir()

    from agent_harness import observability

    async def raise_budget(**_):
        raise observability.TokenBudgetExceeded("token cap 10 exceeded (total=11)")

    with patch("agent_harness.discovery.workflow.run_discovery", new=AsyncMock(side_effect=raise_budget)):
        resp = client.post("/discover", json={
            "repo_id": "synth", "repo_path": str(repo_root),
        })
    assert resp.status_code == 402
    assert "token cap" in resp.json()["detail"]


def test_discover_sets_trace_and_token_counter(client, tmp_path):
    repo_root = tmp_path / "synth"
    repo_root.mkdir()

    captured = {}

    async def capture_ctx(**_):
        from agent_harness import observability
        captured["trace"] = observability.TRACE_ID.get()
        captured["counter"] = observability.TOKEN_COUNTER.get()
        return {"status": "ok", "stages": [], "artifacts": {}}

    with patch("agent_harness.discovery.workflow.run_discovery", new=AsyncMock(side_effect=capture_ctx)):
        resp = client.post("/discover", json={
            "repo_id": "synth", "repo_path": str(repo_root),
        })
    assert resp.status_code == 200
    assert captured["trace"].startswith("discover-")
    assert captured["counter"] is not None
