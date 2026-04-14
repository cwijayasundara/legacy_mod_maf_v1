from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.eval.__main__ import main


@pytest.mark.asyncio
async def test_cli_run_deterministic_exits_zero_on_pass(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from agent_harness.eval.judge import JudgeScore
    js = JudgeScore(raw_overall=8.0, normalised=0.8, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)), \
         patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        code = await main(["run", "--corpus", "synthetic", "--tier", "deterministic",
                           "--out", str(tmp_path / "out")])
    assert code == 0
    assert any((tmp_path / "out").iterdir())


@pytest.mark.asyncio
async def test_cli_run_unknown_corpus_exits_two(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = await main(["run", "--corpus", "does-not-exist",
                       "--tier", "deterministic", "--out", str(tmp_path / "out")])
    assert code == 2


@pytest.mark.asyncio
async def test_cli_run_exits_one_on_stage_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from agent_harness.eval.judge import JudgeScore
    js = JudgeScore(raw_overall=0.0, normalised=0.0, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)), \
         patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        code = await main(["run", "--corpus", "synthetic", "--tier", "deterministic",
                           "--out", str(tmp_path / "out")])
    assert code == 1
