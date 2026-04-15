import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent_harness.discovery.artifacts import (
    AcceptanceCriterion, Backlog, BacklogItem, Epic, Story, Stories,
)
from agent_harness.discovery import paths as discovery_paths
from agent_harness.fanout import migrate_repo, RepoMigrationResult, ModuleOutcome
from agent_harness.persistence.repository import MigrationRepository
from agent_harness.pipeline import PipelineResult


def _write_artifacts(tmp_path, backlog_items, stories_pairs):
    repo_dir = discovery_paths.repo_dir("synth")
    repo_dir.mkdir(parents=True, exist_ok=True)
    backlog = Backlog(items=backlog_items)
    (repo_dir / "backlog.json").write_text(backlog.model_dump_json())
    stories = Stories(
        epics=[Epic(id=f"E-{m}", module_id=m, title="E",
                    story_ids=[sid])
               for (m, sid, _deps) in stories_pairs],
        stories=[Story(id=sid, epic_id=f"E-{m}", title="t", description="d",
                       acceptance_criteria=[AcceptanceCriterion(text="ac")],
                       depends_on=list(deps), blocks=[], estimate="M")
                 for (m, sid, deps) in stories_pairs],
    )
    (repo_dir / "stories.json").write_text(stories.model_dump_json())


def _item(module, wave, sid):
    return BacklogItem(module=module, language="python", work_item_id=sid,
                       title="", description="", acceptance_criteria="",
                       wave=wave)


@pytest.fixture
def repo(tmp_path):
    r = MigrationRepository(db_path=tmp_path / "t.db")
    r.initialize()
    r.create_discovery_run("synth")
    r.approve_backlog("synth", approver="tester")
    return r


@pytest.fixture
def pipeline_stub():
    p = AsyncMock()
    p.run = AsyncMock(return_value=PipelineResult(
        module="orders", status="completed", message="", review_score=90,
    ))
    return p


@pytest.mark.asyncio
async def test_unapproved_backlog_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = MigrationRepository(db_path=tmp_path / "t.db")
    r.initialize()
    r.create_discovery_run("synth")  # not approved
    _write_artifacts(tmp_path, [_item("orders", 1, "S1")],
                     [("orders", "S1", [])])
    p = AsyncMock()
    with pytest.raises(PermissionError):
        await migrate_repo(repo_id="synth", repo=r, pipeline=p)


@pytest.mark.asyncio
async def test_missing_backlog_raises(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    p = AsyncMock()
    with pytest.raises(FileNotFoundError):
        await migrate_repo(repo_id="synth", repo=repo, pipeline=p)


@pytest.mark.asyncio
async def test_all_modules_complete(tmp_path, monkeypatch, repo, pipeline_stub):
    monkeypatch.chdir(tmp_path)
    _write_artifacts(tmp_path,
        [_item("orders", 1, "S1"), _item("payments", 2, "S2")],
        [("orders", "S1", []), ("payments", "S2", ["S1"])])
    result = await migrate_repo(repo_id="synth", repo=repo, pipeline=pipeline_stub)
    assert result.status == "completed"
    assert {m.module: m.status for m in result.modules} == {
        "orders": "completed", "payments": "completed"
    }
    assert pipeline_stub.run.await_count == 2


@pytest.mark.asyncio
async def test_failure_propagates_skip_to_dependent(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    _write_artifacts(tmp_path,
        [_item("orders", 1, "S1"),
         _item("payments", 2, "S2"),
         _item("notifications", 2, "S3")],
        [("orders", "S1", []),
         ("payments", "S2", ["S1"]),
         ("notifications", "S3", [])])

    def fake_result(module, **_):
        if module == "orders":
            return PipelineResult(module="orders", status="failed",
                                  message="boom", review_score=None)
        return PipelineResult(module=module, status="completed",
                              message="", review_score=80)

    p = AsyncMock()
    p.run = AsyncMock(side_effect=lambda module, **kw: fake_result(module, **kw))

    result = await migrate_repo(repo_id="synth", repo=repo, pipeline=p)
    by_mod = {m.module: m for m in result.modules}
    assert by_mod["orders"].status == "failed"
    assert by_mod["payments"].status == "skipped"
    assert "orders" in by_mod["payments"].reason
    assert by_mod["notifications"].status == "completed"
    assert result.status == "partial"
    called_modules = {c.kwargs.get("module") for c in p.run.await_args_list}
    assert "payments" not in called_modules


@pytest.mark.asyncio
async def test_intra_wave_concurrency(tmp_path, monkeypatch, repo):
    """Two independent modules in the same wave should run in parallel."""
    monkeypatch.chdir(tmp_path)
    _write_artifacts(tmp_path,
        [_item("a", 1, "SA"), _item("b", 1, "SB")],
        [("a", "SA", []), ("b", "SB", [])])

    both_entered = asyncio.Event()
    entered = {"count": 0}

    async def slow_run(module, **_):
        entered["count"] += 1
        if entered["count"] == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=1.0)
        return PipelineResult(module=module, status="completed",
                              message="", review_score=85)

    p = AsyncMock()
    p.run = AsyncMock(side_effect=slow_run)
    result = await migrate_repo(repo_id="synth", repo=repo, pipeline=p)
    assert result.status == "completed"
    assert both_entered.is_set()


@pytest.mark.asyncio
async def test_persists_outcomes(tmp_path, monkeypatch, repo, pipeline_stub):
    monkeypatch.chdir(tmp_path)
    _write_artifacts(tmp_path, [_item("orders", 1, "S1")],
                     [("orders", "S1", [])])
    await migrate_repo(repo_id="synth", repo=repo, pipeline=pipeline_stub)
    run = repo.get_migrate_repo_run("synth")
    assert run["status"] == "completed"
    assert len(run["modules"]) == 1
    assert run["modules"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_duplicate_story_backlog_items_collapse_to_single_module_run(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    _write_artifacts(
        tmp_path,
        [
            _item("orders", 1, "S1"),
            _item("orders", 2, "S2"),
            _item("payments", 3, "S3"),
        ],
        [
            ("orders", "S1", []),
            ("orders", "S2", ["S1"]),
            ("payments", "S3", ["S2"]),
        ],
    )

    p = AsyncMock()
    p.run = AsyncMock(side_effect=lambda module, **_: PipelineResult(
        module=module, status="completed", message="", review_score=88
    ))

    result = await migrate_repo(repo_id="synth", repo=repo, pipeline=p)

    assert result.status == "completed"
    assert [m.module for m in result.modules] == ["orders", "payments"]
    assert [m.wave for m in result.modules] == [1, 2]
    assert p.run.await_count == 2
