from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    DependencyGraph, GraphEdge, GraphNode, Inventory, ModuleRecord,
)
from agent_harness.eval.judge import JudgeScore
from agent_harness.eval.scorers.design import score


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


_GOOD_DESIGN = (
    "## Function Plan\nFlex\n"
    "## Trigger Bindings\n- HTTP trigger\n"
    "## State Mapping\n- dynamodb_table:Orders → Cosmos DB NoSQL\n"
    "## Secrets\n- KV\n## Identity\n- Managed Identity\n"
    "## IaC\n- Bicep\n## Observability\n- App Insights\n"
)

_BAD_DESIGN = "## Function Plan\nFlex\n"


@pytest.mark.asyncio
async def test_design_scorer_passes_when_structural_and_judge_both_pass():
    js = JudgeScore(raw_overall=8.0, normalised=0.8, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score({"orders": _GOOD_DESIGN}, _inv(), _graph())
    assert r.stage == "design"
    assert r.passed is True


@pytest.mark.asyncio
async def test_design_scorer_fails_when_sections_missing():
    js = JudgeScore(raw_overall=10.0, normalised=1.0, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score({"orders": _BAD_DESIGN}, _inv(), _graph())
    assert r.passed is False
    assert r.details["structural"]["orders"]["missing_sections"]


@pytest.mark.asyncio
async def test_design_scorer_fails_when_module_missing_design():
    js = JudgeScore(raw_overall=10.0, normalised=1.0, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score({}, _inv(), _graph())
    assert r.passed is False
    assert "orders" in r.details["missing_module_designs"]


@pytest.mark.asyncio
async def test_design_scorer_threshold_is_0_7():
    js = JudgeScore(raw_overall=7.0, normalised=0.7, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score({"orders": _GOOD_DESIGN}, _inv(), _graph())
    assert r.threshold == 0.7
