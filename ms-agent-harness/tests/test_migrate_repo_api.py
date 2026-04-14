from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agent_harness.fanout import RepoMigrationResult, ModuleOutcome


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from agent_harness.orchestrator import api as api_mod
    api_mod._pipeline = None  # real pipeline not needed; mocked
    api_mod._ado = None
    from agent_harness.persistence.repository import MigrationRepository
    api_mod._discovery_repo = MigrationRepository(db_path=tmp_path / "disc.db")
    api_mod._discovery_repo.initialize()
    return TestClient(api_mod.app)


def test_migrate_repo_sync_not_approved_returns_409(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    resp = client.post("/migrate-repo/sync", json={"repo_id": "synth"})
    assert resp.status_code == 409


def test_migrate_repo_sync_returns_result(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    api_mod._discovery_repo.approve_backlog("synth", approver="t")

    fake = RepoMigrationResult(repo_id="synth", run_id=1, status="completed",
        modules=[ModuleOutcome(module="orders", wave=1, status="completed",
                                review_score=80)])
    with patch("agent_harness.fanout.migrate_repo",
               new=AsyncMock(return_value=fake)):
        resp = client.post("/migrate-repo/sync", json={"repo_id": "synth"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["modules"][0]["module"] == "orders"


def test_migrate_repo_background_returns_accepted(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    api_mod._discovery_repo.approve_backlog("synth", approver="t")

    fake = RepoMigrationResult(repo_id="synth", run_id=1, status="completed", modules=[])
    with patch("agent_harness.fanout.migrate_repo",
               new=AsyncMock(return_value=fake)):
        resp = client.post("/migrate-repo", json={"repo_id": "synth"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


def test_migrate_repo_background_rejects_unapproved(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    resp = client.post("/migrate-repo", json={"repo_id": "synth"})
    assert resp.status_code == 409


def test_get_migrate_repo_404_when_no_run(client):
    resp = client.get("/migrate-repo/unknown")
    assert resp.status_code == 404


def test_get_migrate_repo_returns_run(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    run_id = api_mod._discovery_repo.create_migrate_repo_run("synth")
    api_mod._discovery_repo.record_migrate_module(run_id, "orders", wave=1,
                                                   status="completed",
                                                   review_score=90)
    resp = client.get("/migrate-repo/synth")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo_id"] == "synth"
    assert body["modules"][0]["module"] == "orders"
