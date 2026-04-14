from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    DependencyGraph, GraphEdge, GraphNode, Inventory, ModuleRecord,
)
from agent_harness.eval.judge import JudgeScore
from agent_harness.eval.scorers.brd import score


def _inv():
    return Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path="orders", language="python",
                              handler_entrypoint="orders/handler.py",
                              loc=1, config_files=[])],
    )


def _graph():
    return DependencyGraph(
        nodes=[GraphNode(id="orders", kind="module", attrs={}),
               GraphNode(id="dynamodb_table:Orders", kind="aws_resource",
                         attrs={"resource_kind": "dynamodb_table"})],
        edges=[GraphEdge(src="orders", dst="dynamodb_table:Orders", kind="writes")],
    )


_GOOD_BODY = (
    "## Purpose\nx\n## Triggers\nHTTP\n## Inputs\nx\n## Outputs\nx\n"
    "## Business Rules\n- idempotent\n"
    "## Side Effects\n- writes dynamodb_table:Orders\n"
    "## Error Paths\n- returns 500\n"
    "## Non-Functionals\n- low latency\n## PII/Compliance\n- none\n"
)

_BAD_BODY = "## Purpose\nx\n"


@pytest.mark.asyncio
async def test_brd_scorer_passes_when_structural_and_judge_both_pass():
    inv = _inv()
    graph = _graph()
    brd = {"orders": _GOOD_BODY}
    js = JudgeScore(raw_overall=8.0, normalised=0.8,
                     per_criterion={"faithfulness": 8, "resource_coverage": 8,
                                    "trigger_coverage": 8},
                     reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score(brd, inv, graph)
    assert r.stage == "brd"
    assert r.passed is True
    assert r.score >= r.threshold


@pytest.mark.asyncio
async def test_brd_scorer_fails_when_sections_missing():
    inv = _inv()
    graph = _graph()
    brd = {"orders": _BAD_BODY}
    js = JudgeScore(raw_overall=10.0, normalised=1.0, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score(brd, inv, graph)
    assert r.passed is False
    assert r.details["structural"]["orders"]["missing_sections"]


@pytest.mark.asyncio
async def test_brd_scorer_fails_when_module_missing_brd():
    inv = _inv()
    graph = _graph()
    brd: dict[str, str] = {}
    js = JudgeScore(raw_overall=10.0, normalised=1.0, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score(brd, inv, graph)
    assert r.passed is False
    assert "orders" in r.details["missing_module_brds"]


@pytest.mark.asyncio
async def test_brd_scorer_fails_when_judge_scores_low():
    inv = _inv()
    graph = _graph()
    brd = {"orders": _GOOD_BODY}
    js = JudgeScore(raw_overall=2.0, normalised=0.2, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score(brd, inv, graph)
    assert r.passed is False


@pytest.mark.asyncio
async def test_brd_scorer_threshold_is_0_7():
    inv = _inv()
    graph = _graph()
    js = JudgeScore(raw_overall=7.0, normalised=0.7, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score({"orders": _GOOD_BODY}, inv, graph)
    assert r.threshold == 0.7
