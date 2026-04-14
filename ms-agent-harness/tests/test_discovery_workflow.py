from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent_harness.discovery.workflow import (
    run_stage, hash_inputs,
)
from agent_harness.discovery.artifacts import CriticReport
from agent_harness.discovery import paths
from agent_harness.persistence.repository import MigrationRepository


@pytest.fixture
def repo(tmp_path):
    r = MigrationRepository(db_path=tmp_path / "test.db")
    r.initialize()
    return r


def test_hash_inputs_stable():
    h1 = hash_inputs("repo", "scanner", ["a", "b"], prompt_version="v1")
    h2 = hash_inputs("repo", "scanner", ["a", "b"], prompt_version="v1")
    assert h1 == h2
    h3 = hash_inputs("repo", "scanner", ["a", "b"], prompt_version="v2")
    assert h1 != h3


@pytest.mark.asyncio
async def test_run_stage_succeeds_first_try(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    repo.create_discovery_run("synth")
    produce = AsyncMock(return_value="ARTIFACT")
    critic = lambda result, ctx: CriticReport(verdict="PASS", reasons=[], suggestions=[])

    out = await run_stage(
        repo=repo, repo_id="synth", stage_name="scanner",
        produce=produce, critic=critic,
        artifact_path=tmp_path / "discovery" / "synth" / "scanner.txt",
        input_hash="h1",
    )

    assert out == "ARTIFACT"
    produce.assert_awaited_once_with("")
    assert repo.stage_cache_hit("synth", "scanner", "h1")


@pytest.mark.asyncio
async def test_run_stage_self_heals_then_passes(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    repo.create_discovery_run("synth")
    produce = AsyncMock(side_effect=["BAD1", "BAD2", "GOOD"])
    verdicts = iter([
        CriticReport(verdict="FAIL", reasons=["r1"], suggestions=["s1"]),
        CriticReport(verdict="FAIL", reasons=["r2"], suggestions=["s2"]),
        CriticReport(verdict="PASS", reasons=[], suggestions=[]),
    ])
    critic = lambda result, ctx: next(verdicts)

    out = await run_stage(
        repo=repo, repo_id="synth", stage_name="scanner",
        produce=produce, critic=critic,
        artifact_path=tmp_path / "discovery" / "synth" / "scanner.txt",
        input_hash="h1",
    )
    assert out == "GOOD"
    assert produce.await_count == 3
    assert "r1" in produce.await_args_list[1].args[0]
    assert "r2" in produce.await_args_list[2].args[0]


@pytest.mark.asyncio
async def test_run_stage_blocks_after_three_fails(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    repo.create_discovery_run("synth")
    produce = AsyncMock(side_effect=["B1", "B2", "B3"])
    critic = lambda result, ctx: CriticReport(verdict="FAIL", reasons=["nope"], suggestions=[])
    artifact = tmp_path / "discovery" / "synth" / "scanner.txt"

    with pytest.raises(RuntimeError, match="blocked"):
        await run_stage(
            repo=repo, repo_id="synth", stage_name="scanner",
            produce=produce, critic=critic,
            artifact_path=artifact, input_hash="h1",
        )
    assert paths.blocked_path("synth", "scanner").exists()
    assert not repo.stage_cache_hit("synth", "scanner", "h1")


@pytest.mark.asyncio
async def test_cache_hit_skips_produce(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    repo.create_discovery_run("synth")
    artifact = tmp_path / "discovery" / "synth" / "scanner.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("CACHED")
    repo.cache_stage("synth", "scanner", "h1", str(artifact))
    produce = AsyncMock(return_value="NEW")
    critic = lambda result, ctx: CriticReport(verdict="PASS", reasons=[], suggestions=[])

    out = await run_stage(
        repo=repo, repo_id="synth", stage_name="scanner",
        produce=produce, critic=critic, artifact_path=artifact, input_hash="h1",
    )
    assert out == "CACHED"
    produce.assert_not_called()
