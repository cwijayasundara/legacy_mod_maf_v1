import pytest
from agent_harness.persistence.repository import MigrationRepository


@pytest.fixture
def repo(tmp_path):
    r = MigrationRepository(db_path=tmp_path / "test.db")
    r.initialize()
    return r


def test_create_migrate_repo_run_returns_id(repo):
    run_id = repo.create_migrate_repo_run("my-repo")
    assert isinstance(run_id, int) and run_id > 0


def test_record_module_and_get(repo):
    run_id = repo.create_migrate_repo_run("my-repo")
    repo.record_migrate_module(run_id, "orders", wave=1,
                                status="completed", review_score=87)
    repo.record_migrate_module(run_id, "payments", wave=2,
                                status="skipped", reason="orders failed")
    run = repo.get_migrate_repo_run("my-repo")
    assert run["status"] == "running"
    modules = {m["module"]: m for m in run["modules"]}
    assert modules["orders"]["status"] == "completed"
    assert modules["orders"]["review_score"] == 87
    assert modules["payments"]["status"] == "skipped"
    assert modules["payments"]["reason"] == "orders failed"


def test_complete_migrate_repo_run(repo):
    run_id = repo.create_migrate_repo_run("my-repo")
    repo.complete_migrate_repo_run(run_id, "partial")
    run = repo.get_migrate_repo_run("my-repo")
    assert run["status"] == "partial"
    assert run["completed_at"] is not None


def test_get_returns_latest_run(repo):
    r1 = repo.create_migrate_repo_run("my-repo")
    repo.complete_migrate_repo_run(r1, "failed")
    r2 = repo.create_migrate_repo_run("my-repo")
    run = repo.get_migrate_repo_run("my-repo")
    assert run["id"] == r2
    assert run["status"] == "running"


def test_get_returns_none_for_unknown_repo(repo):
    assert repo.get_migrate_repo_run("ghost") is None


def test_update_module_status(repo):
    """record_migrate_module should upsert on (run_id, module)."""
    run_id = repo.create_migrate_repo_run("my-repo")
    repo.record_migrate_module(run_id, "orders", wave=1, status="running")
    repo.record_migrate_module(run_id, "orders", wave=1,
                                status="completed", review_score=90)
    run = repo.get_migrate_repo_run("my-repo")
    assert len(run["modules"]) == 1
    assert run["modules"][0]["status"] == "completed"
    assert run["modules"][0]["review_score"] == 90
