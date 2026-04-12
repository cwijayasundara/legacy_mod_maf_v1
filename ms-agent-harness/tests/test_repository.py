"""Tests for agents/persistence/repository.py — SQLite persistence, no LLM calls.

Each test gets an isolated SQLite database via tmp_path.
"""

from agent_harness.persistence.repository import MigrationRepository


def _repo(tmp_path):
    """Create a MigrationRepository backed by a temp SQLite file."""
    db = tmp_path / "test_migration.db"
    repo = MigrationRepository(db_path=str(db))
    repo.initialize()
    return repo


class TestStartAndCompleteRun:
    def test_start_run_returns_id(self, tmp_path):
        repo = _repo(tmp_path)
        run_id = repo.start_run("handler.py", "python")
        assert isinstance(run_id, int)
        assert run_id >= 1

    def test_complete_run_updates_status(self, tmp_path):
        repo = _repo(tmp_path)
        run_id = repo.start_run("handler.py", "python")
        repo.complete_run(run_id, "completed")
        last = repo.get_last_run("handler.py")
        assert last is not None
        assert last["status"] == "completed"
        assert last["completed_at"] is not None

    def test_complete_run_with_error(self, tmp_path):
        repo = _repo(tmp_path)
        run_id = repo.start_run("handler.py", "python")
        repo.complete_run(run_id, "failed", error="timeout")
        last = repo.get_last_run("handler.py")
        assert last["status"] == "failed"
        assert last["error_message"] == "timeout"

    def test_get_last_run_nonexistent(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.get_last_run("nonexistent.py") is None


class TestCacheAnalysis:
    def test_cache_and_retrieve(self, tmp_path):
        repo = _repo(tmp_path)
        analysis = {"imports": ["boto3"], "functions": 5, "complexity": "MEDIUM"}
        repo.cache_analysis("handler.py", analysis, score=8, level="MEDIUM")

        cached = repo.get_cached_analysis("handler.py")
        assert cached is not None
        assert cached["imports"] == ["boto3"]
        assert cached["functions"] == 5

    def test_cache_overwrite(self, tmp_path):
        repo = _repo(tmp_path)
        repo.cache_analysis("handler.py", {"v": 1}, score=5, level="LOW")
        repo.cache_analysis("handler.py", {"v": 2}, score=10, level="MEDIUM")
        cached = repo.get_cached_analysis("handler.py")
        assert cached["v"] == 2

    def test_cache_miss(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.get_cached_analysis("nope.py") is None


class TestChunkStatus:
    def test_init_chunks(self, tmp_path):
        repo = _repo(tmp_path)
        repo.init_chunks("handler.py", 5)
        results = repo.get_chunk_results("handler.py")
        assert len(results) == 5
        assert all(r["status"] == "pending" for r in results)

    def test_update_chunk_status(self, tmp_path):
        repo = _repo(tmp_path)
        repo.init_chunks("handler.py", 3)
        repo.update_chunk("handler.py", 0, "completed", tokens_used=100, result="ok")
        results = repo.get_chunk_results("handler.py")
        assert results[0]["status"] == "completed"
        assert results[0]["tokens_used"] == 100
        assert results[1]["status"] == "pending"

    def test_get_last_completed_chunk_none(self, tmp_path):
        repo = _repo(tmp_path)
        repo.init_chunks("handler.py", 3)
        assert repo.get_last_completed_chunk("handler.py") == -1


class TestCheckpointResume:
    def test_checkpoint_resume(self, tmp_path):
        """Complete chunks 0-2, verify last_completed=2."""
        repo = _repo(tmp_path)
        repo.init_chunks("handler.py", 5)
        for i in range(3):
            repo.update_chunk("handler.py", i, "completed", tokens_used=50)

        last = repo.get_last_completed_chunk("handler.py")
        assert last == 2

    def test_partial_completion(self, tmp_path):
        repo = _repo(tmp_path)
        repo.init_chunks("handler.py", 5)
        repo.update_chunk("handler.py", 0, "completed")
        repo.update_chunk("handler.py", 1, "failed", error="timeout")
        repo.update_chunk("handler.py", 2, "completed")
        # Last completed is 2 (even though 1 failed)
        assert repo.get_last_completed_chunk("handler.py") == 2


class TestDependencies:
    def test_add_and_retrieve(self, tmp_path):
        repo = _repo(tmp_path)
        repo.add_dependency("handler.py", "utils.py", dep_type="imports", details="from utils import helper")
        repo.add_dependency("handler.py", "models.py", dep_type="calls", details="models.Order")

        deps = repo.get_dependencies("handler.py")
        assert len(deps) == 2
        targets = {d["target_module"] for d in deps}
        assert "utils.py" in targets
        assert "models.py" in targets

    def test_bidirectional_lookup(self, tmp_path):
        repo = _repo(tmp_path)
        repo.add_dependency("a.py", "b.py", dep_type="calls")
        # Lookup from b.py side
        deps = repo.get_dependencies("b.py")
        assert len(deps) == 1
        assert deps[0]["source_module"] == "a.py"

    def test_no_dependencies(self, tmp_path):
        repo = _repo(tmp_path)
        assert repo.get_dependencies("orphan.py") == []
