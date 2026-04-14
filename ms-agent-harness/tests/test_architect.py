from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, DependencyGraph, GraphNode, GraphEdge,
    ModuleBRD, SystemBRD, ModuleDesign, SystemDesign,
)
from agent_harness.discovery.architect import design
from agent_harness.discovery.critics.design_critic import critique_designs
from agent_harness.discovery import paths

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


def _inv():
    return Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path="orders", language="python",
                              handler_entrypoint="orders/handler.py",
                              loc=14, config_files=[])],
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
async def test_design_writes_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module_design = (
        "# Module Design: orders\n\n"
        "## Function Plan\nFlex consumption.\n\n"
        "## Trigger Bindings\n- HTTP trigger.\n\n"
        "## State Mapping\n- dynamodb_table:Orders → Cosmos DB NoSQL container.\n\n"
        "## Secrets\n- None.\n\n"
        "## Identity\n- Managed Identity.\n\n"
        "## IaC\n- Bicep.\n\n"
        "## Observability\n- App Insights.\n"
    )
    system = "# System Design\n\n## Strangler Seams\nMigrate orders first.\n"
    brd = ModuleBRD(module_id="orders", body=(
        "## Triggers\nAPI Gateway POST /orders.\n## Side Effects\n- writes dynamodb_table:Orders\n"
    ))
    sys_brd = SystemBRD(body="ok")
    with patch("agent_harness.discovery.architect._run_module_agent",
               new=AsyncMock(return_value=module_design)), \
         patch("agent_harness.discovery.architect._run_system_agent",
               new=AsyncMock(return_value=system)):
        modules, sysd = await design(
            repo_id="synth", inventory=_inv(), graph=_graph(),
            module_brds=[brd], system_brd=sys_brd,
        )
    assert paths.module_design_path("synth", "orders").exists()
    assert paths.system_design_path("synth").exists()
    assert "Cosmos DB" in modules[0].body


def test_design_critic_fails_when_resource_unmapped():
    md = ModuleDesign(module_id="orders", body=(
        "## State Mapping\n- nothing\n"
    ))
    sd = SystemDesign(body="ok")
    report = critique_designs(
        designs=[md], system=sd, inventory=_inv(),
        graph=_graph(), module_brds=[ModuleBRD(module_id="orders", body="x")],
    )
    assert report.verdict == "FAIL"
    assert any("dynamodb_table" in r for r in report.reasons)


def test_design_critic_passes_when_resource_mapped():
    md = ModuleDesign(module_id="orders", body=(
        "## State Mapping\n- dynamodb_table:Orders → Cosmos DB NoSQL\n"
    ))
    sd = SystemDesign(body="ok")
    report = critique_designs(
        designs=[md], system=sd, inventory=_inv(), graph=_graph(),
        module_brds=[ModuleBRD(module_id="orders", body="x")],
    )
    assert report.verdict == "PASS"
