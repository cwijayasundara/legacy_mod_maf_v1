from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, DependencyGraph, GraphNode, GraphEdge,
)
from agent_harness.discovery.brd_extractor import extract_brds
from agent_harness.discovery.critics.brd_critic import critique_brds
from agent_harness.discovery import paths

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


def _inv():
    return Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 8, "total_loc": 60,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py", loc=14, config_files=[]),
        ],
    )


def _graph():
    return DependencyGraph(
        nodes=[
            GraphNode(id="orders", kind="module", attrs={}),
            GraphNode(id="dynamodb_table:Orders", kind="aws_resource",
                      attrs={"resource_kind": "dynamodb_table"}),
        ],
        edges=[GraphEdge(src="orders", dst="dynamodb_table:Orders", kind="writes")],
    )


@pytest.mark.asyncio
async def test_extract_brds_writes_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    canned = (
        "# Module BRD: orders\n\n"
        "## Purpose\nReceives orders.\n\n"
        "## Triggers\nAPI Gateway POST /orders.\n\n"
        "## Business Rules\n- Idempotent on order id.\n\n"
        "## Side Effects\n- Writes dynamodb_table:Orders.\n\n"
        "## Error Paths\n- Returns 500 on DynamoDB failure.\n"
    )
    sysbrd = "# System BRD\n\n## Cross-Module Workflows\nNone.\n"
    with patch("agent_harness.discovery.brd_extractor._run_module_agent",
               new=AsyncMock(return_value=canned)), \
         patch("agent_harness.discovery.brd_extractor._run_system_agent",
               new=AsyncMock(return_value=sysbrd)):
        modules, system = await extract_brds(
            repo_id="synth", repo_root=FIXTURE, inventory=_inv(), graph=_graph(),
        )
    assert paths.module_brd_path("synth", "orders").exists()
    assert paths.system_brd_path("synth").exists()
    assert "Business Rules" in modules[0].body
    assert "System BRD" in system.body


def test_brd_critic_passes_when_all_required_sections_present(tmp_path):
    from agent_harness.discovery.artifacts import ModuleBRD, SystemBRD
    body = (
        "# Module BRD: orders\n\n"
        "## Business Rules\n- rule\n\n"
        "## Error Paths\n- err\n\n"
        "## Side Effects\n- writes dynamodb_table:Orders\n"
    )
    report = critique_brds(
        modules=[ModuleBRD(module_id="orders", body=body)],
        system=SystemBRD(body="ok"),
        inventory=_inv(),
        graph=_graph(),
    )
    assert report.verdict == "PASS", report.reasons


def test_brd_critic_fails_when_business_rules_missing():
    from agent_harness.discovery.artifacts import ModuleBRD, SystemBRD
    body = "# Module BRD: orders\n\n## Side Effects\n- writes dynamodb_table:Orders\n"
    report = critique_brds(
        modules=[ModuleBRD(module_id="orders", body=body)],
        system=SystemBRD(body="ok"),
        inventory=_inv(),
        graph=_graph(),
    )
    assert report.verdict == "FAIL"
    assert any("business_rules" in r.lower() or "business rules" in r.lower()
               for r in report.reasons)


def test_brd_critic_fails_when_module_missing():
    from agent_harness.discovery.artifacts import SystemBRD
    report = critique_brds(
        modules=[],
        system=SystemBRD(body="ok"),
        inventory=_inv(),
        graph=_graph(),
    )
    assert report.verdict == "FAIL"
    assert any("orders" in r for r in report.reasons)


def test_brd_critic_fails_when_resource_unreferenced():
    from agent_harness.discovery.artifacts import ModuleBRD, SystemBRD
    body = (
        "# Module BRD: orders\n\n"
        "## Business Rules\n- r\n\n"
        "## Error Paths\n- e\n\n"
        "## Side Effects\n- nothing\n"
    )
    report = critique_brds(
        modules=[ModuleBRD(module_id="orders", body=body)],
        system=SystemBRD(body="ok"),
        inventory=_inv(),
        graph=_graph(),
    )
    assert report.verdict == "FAIL"
    assert any("Orders" in r for r in report.reasons)
