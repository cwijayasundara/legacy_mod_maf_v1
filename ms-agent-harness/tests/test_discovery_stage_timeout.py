import asyncio

import pytest

from agent_harness.discovery.artifacts import CriticReport
from agent_harness.discovery.workflow import run_stage
from agent_harness.persistence.repository import MigrationRepository


@pytest.fixture
def repo(tmp_path):
    r = MigrationRepository(db_path=tmp_path / "t.db")
    r.initialize()
    r.create_discovery_run("synth")
    return r


@pytest.mark.asyncio
async def test_stage_timeout_treated_as_failed_critic(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    call_count = {"n": 0}

    async def slow_produce(feedback: str) -> str:
        call_count["n"] += 1
        await asyncio.sleep(1.0)
        return "never"

    def critic(result: str, ctx: dict) -> CriticReport:
        return CriticReport(verdict="PASS", reasons=[], suggestions=[])

    artifact = tmp_path / "discovery" / "synth" / "scanner.txt"
    with pytest.raises(RuntimeError, match="blocked"):
        await run_stage(
            repo=repo, repo_id="synth", stage_name="scanner",
            produce=slow_produce, critic=critic,
            artifact_path=artifact, input_hash="h1",
            stage_timeout=0.05,
        )
    assert call_count["n"] == 3


@pytest.mark.asyncio
async def test_stage_timeout_none_keeps_old_behaviour(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)

    async def fast_produce(feedback: str) -> str:
        return "ok"

    def critic(result: str, ctx: dict) -> CriticReport:
        return CriticReport(verdict="PASS", reasons=[], suggestions=[])

    artifact = tmp_path / "discovery" / "synth" / "scanner.txt"
    out = await run_stage(
        repo=repo, repo_id="synth", stage_name="scanner",
        produce=fast_produce, critic=critic,
        artifact_path=artifact, input_hash="h1",
        stage_timeout=None,
    )
    assert out == "ok"
