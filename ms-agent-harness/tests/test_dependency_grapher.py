from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from agent_harness.discovery.artifacts import Inventory, ModuleRecord
from agent_harness.discovery.dependency_grapher import build_graph
from agent_harness.discovery.critics.graph_critic import critique_graph
from agent_harness.discovery import paths

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


def _inv() -> Inventory:
    return Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 8, "total_loc": 60,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py", loc=14, config_files=[]),
            ModuleRecord(id="payments", path="payments", language="python",
                         handler_entrypoint="payments/handler.py", loc=18, config_files=[]),
            ModuleRecord(id="notifications", path="notifications", language="python",
                         handler_entrypoint="notifications/handler.py", loc=12, config_files=[]),
        ],
    )


@pytest.mark.asyncio
async def test_build_graph_deterministic_path(tmp_path, monkeypatch):
    """When all calls resolve via aws_sdk_patterns, no LLM is invoked."""
    monkeypatch.chdir(tmp_path)
    with patch("agent_harness.discovery.dependency_grapher._run_agent",
               new=AsyncMock(return_value="[]")) as fake:
        g = await build_graph(repo_id="synth", repo_root=FIXTURE, inventory=_inv())
    fake.assert_not_called()

    edges = {(e.src, e.dst, e.kind) for e in g.edges}
    assert ("orders", "dynamodb_table:Orders", "writes") in edges
    assert ("orders", "sqs_queue:payments-queue", "produces") in edges
    assert ("payments", "dynamodb_table:Orders", "reads") in edges
    assert ("payments", "dynamodb_table:Payments", "writes") in edges
    assert ("payments", "sns_topic:payment-events", "produces") in edges
    assert ("notifications", "secrets_manager_secret:webhook/url", "reads") in edges


@pytest.mark.asyncio
async def test_graph_critic_passes_on_complete_graph(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with patch("agent_harness.discovery.dependency_grapher._run_agent",
               new=AsyncMock(return_value="[]")):
        g = await build_graph(repo_id="synth", repo_root=FIXTURE, inventory=_inv())
    report = critique_graph(g, repo_root=FIXTURE, inventory=_inv())
    assert report.verdict == "PASS", report.reasons


def test_graph_critic_fails_when_edge_missing():
    from agent_harness.discovery.artifacts import DependencyGraph, GraphNode, GraphEdge
    g = DependencyGraph(
        nodes=[GraphNode(id="orders", kind="module", attrs={})],
        edges=[],  # no edges
    )
    report = critique_graph(g, repo_root=FIXTURE, inventory=_inv())
    assert report.verdict == "FAIL"
    assert any("Orders" in r or "put_item" in r for r in report.reasons)
