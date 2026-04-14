import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.eval.judge import Judge, Rubric, load_rubric, JudgeScore

RUBRICS = Path(__file__).parent.parent / "agent_harness" / "eval" / "rubrics"


def test_load_rubric_brd():
    r = load_rubric("brd")
    assert r.name == "brd"
    assert r.criteria
    total_weight = sum(c.weight for c in r.criteria)
    assert abs(total_weight - 1.0) < 1e-6


def test_load_rubric_design():
    r = load_rubric("design")
    assert r.name == "design"
    total_weight = sum(c.weight for c in r.criteria)
    assert abs(total_weight - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_judge_score_parses_valid_json():
    canned = json.dumps({
        "criteria": [
            {"name": "faithfulness", "score": 8, "reasoning": "good"},
            {"name": "resource_coverage", "score": 10, "reasoning": "all present"},
            {"name": "trigger_coverage", "score": 6, "reasoning": "one missing"},
        ],
        "overall": 8.2,
    })
    rubric = load_rubric("brd")
    judge = Judge()
    with patch("agent_harness.eval.judge._run_judge",
               new=AsyncMock(return_value=canned)):
        result = await judge.score(rubric, artifact="body", context={})
    assert isinstance(result, JudgeScore)
    assert 0.0 <= result.normalised <= 1.0
    assert result.raw_overall == 8.2


@pytest.mark.asyncio
async def test_judge_score_handles_fenced_json():
    canned = "```json\n" + json.dumps({
        "criteria": [{"name": "faithfulness", "score": 7, "reasoning": ""},
                     {"name": "resource_coverage", "score": 7, "reasoning": ""},
                     {"name": "trigger_coverage", "score": 7, "reasoning": ""}],
        "overall": 7.0,
    }) + "\n```"
    rubric = load_rubric("brd")
    judge = Judge()
    with patch("agent_harness.eval.judge._run_judge",
               new=AsyncMock(return_value=canned)):
        result = await judge.score(rubric, artifact="body", context={})
    assert result.raw_overall == 7.0


@pytest.mark.asyncio
async def test_judge_score_raises_on_garbage():
    rubric = load_rubric("brd")
    judge = Judge()
    with patch("agent_harness.eval.judge._run_judge",
               new=AsyncMock(return_value="not json at all")):
        with pytest.raises(ValueError, match="could not parse"):
            await judge.score(rubric, artifact="body", context={})


@pytest.mark.asyncio
async def test_judge_model_overridable_via_rubric():
    rubric = load_rubric("brd")
    rubric.judge_model = "gpt-5"
    judge = Judge()
    captured = {}

    async def fake_runner(model, messages, temperature):
        captured["model"] = model
        return json.dumps({
            "criteria": [{"name": "faithfulness", "score": 5, "reasoning": ""},
                         {"name": "resource_coverage", "score": 5, "reasoning": ""},
                         {"name": "trigger_coverage", "score": 5, "reasoning": ""}],
            "overall": 5.0,
        })

    with patch("agent_harness.eval.judge._run_judge", side_effect=fake_runner):
        await judge.score(rubric, artifact="body", context={})
    assert captured["model"] == "gpt-5"
