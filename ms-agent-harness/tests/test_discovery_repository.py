import pytest
from agent_harness.persistence.repository import MigrationRepository


@pytest.fixture
def repo(tmp_path):
    r = MigrationRepository(db_path=tmp_path / "test.db")
    r.initialize()
    return r


def test_create_discovery_run(repo):
    repo.create_discovery_run("my-repo")
    run = repo.get_discovery_run("my-repo")
    assert run["repo_id"] == "my-repo"
    assert run["approved"] == 0


def test_stage_cache_hit_miss(repo):
    repo.create_discovery_run("my-repo")
    assert repo.stage_cache_hit("my-repo", "scanner", "h1") is False
    repo.cache_stage("my-repo", "scanner", "h1", "discovery/my-repo/inventory.json")
    assert repo.stage_cache_hit("my-repo", "scanner", "h1") is True
    assert repo.stage_cache_hit("my-repo", "scanner", "different-hash") is False


def test_stage_cache_overwrites_on_new_hash(repo):
    repo.create_discovery_run("my-repo")
    repo.cache_stage("my-repo", "scanner", "h1", "p1")
    repo.cache_stage("my-repo", "scanner", "h2", "p2")
    assert repo.stage_cache_hit("my-repo", "scanner", "h1") is False
    assert repo.stage_cache_hit("my-repo", "scanner", "h2") is True


def test_approve_backlog(repo):
    repo.create_discovery_run("my-repo")
    repo.approve_backlog("my-repo", approver="alice", comment="lgtm")
    run = repo.get_discovery_run("my-repo")
    assert run["approved"] == 1
    assert run["approver"] == "alice"
    assert run["approval_comment"] == "lgtm"
    assert run["approved_at"] is not None
