from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from agent_harness.orchestrator import api as api_mod
    api_mod._pipeline = None
    api_mod._ado = None
    # Fresh repo per test to avoid cross-test state.
    from agent_harness.persistence.repository import MigrationRepository
    api_mod._discovery_repo = MigrationRepository(db_path=tmp_path / "disc.db")
    api_mod._discovery_repo.initialize()
    return TestClient(api_mod.app)


def test_discover_404_on_missing_path(client):
    resp = client.post("/discover", json={"repo_id": "synth", "repo_path": "/no/such/dir"})
    assert resp.status_code == 404


def test_discover_invokes_workflow(client, tmp_path):
    repo_root = tmp_path / "synth"
    repo_root.mkdir()
    fake_result = {"status": "ok", "stages": [], "artifacts": {}}
    with patch("agent_harness.discovery.workflow.run_discovery",
               new=AsyncMock(return_value=fake_result)):
        resp = client.post("/discover", json={"repo_id": "synth",
                                              "repo_path": str(repo_root)})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_plan_409_when_no_discovery(client):
    resp = client.post("/plan", json={"repo_id": "missing"})
    assert resp.status_code == 409


def test_approve_backlog_flips_flag(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    resp = client.post("/approve/backlog/synth",
                       json={"approver": "alice", "comment": "lgtm"})
    assert resp.status_code == 200
    assert api_mod._discovery_repo.is_backlog_approved("synth")


def test_get_discover_returns_status(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    resp = client.get("/discover/synth")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo_id"] == "synth"
    assert body["approved"] is False
