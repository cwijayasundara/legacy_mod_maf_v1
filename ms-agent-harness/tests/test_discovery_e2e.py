from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.workflow import run_discovery, run_planning
from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, Stories, Story, Epic, AcceptanceCriterion,
)
from agent_harness.discovery import paths
from agent_harness.persistence.repository import MigrationRepository
from agent_harness.discovery.story_decomposer import synthesize_stories

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


@pytest.mark.asyncio
async def test_e2e_synthetic_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = MigrationRepository(db_path=tmp_path / "e2e.db")
    repo.initialize()

    inv_json = Inventory(
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
    ).model_dump_json()

    def _brd_body(refs: list[str]) -> str:
        side = "\n".join(f"- writes/reads {r}" for r in refs)
        return (
            "## Purpose\nx\n\n## Triggers\nx\n\n## Inputs\nx\n\n## Outputs\nx\n\n"
            "## Business Rules\n- r\n\n"
            f"## Side Effects\n{side}\n\n"
            "## Error Paths\n- e\n\n## Non-Functionals\n- n\n\n## PII/Compliance\n- n\n"
        )

    brd_canned = {
        "orders": _brd_body(["dynamodb_table:Orders", "sqs_queue:payments-queue"]),
        "payments": _brd_body(["dynamodb_table:Orders", "dynamodb_table:Payments",
                               "sns_topic:payment-events"]),
        "notifications": _brd_body(["secrets_manager_secret:webhook/url"]),
    }

    def _design_body(refs: list[str]) -> str:
        sm = "\n".join(f"- {r} → Azure target" for r in refs)
        return (
            "## Function Plan\nFlex\n\n## Trigger Bindings\n- HTTP\n\n"
            f"## State Mapping\n{sm}\n\n## Secrets\n- KV\n\n"
            "## Identity\n- MI\n\n## IaC\n- Bicep\n\n## Observability\n- AI\n"
        )

    design_canned = {
        "orders": _design_body(["dynamodb_table:Orders", "sqs_queue:payments-queue"]),
        "payments": _design_body(["dynamodb_table:Orders", "dynamodb_table:Payments",
                                  "sns_topic:payment-events"]),
        "notifications": _design_body(["secrets_manager_secret:webhook/url"]),
    }

    stories_canned = Stories(
        epics=[
            Epic(id="E1", module_id="orders", title="Migrate orders", story_ids=["S1"]),
            Epic(id="E2", module_id="payments", title="Migrate payments", story_ids=["S2"]),
            Epic(id="E3", module_id="notifications", title="Migrate notifications",
                 story_ids=["S3"]),
        ],
        stories=[
            Story(id="S1", epic_id="E1", title="orders fn", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=[], blocks=["S2"], estimate="M"),
            Story(id="S2", epic_id="E2", title="payments fn", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S1"], blocks=["S3"], estimate="M"),
            Story(id="S3", epic_id="E3", title="notifications fn", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S2"], blocks=[], estimate="M"),
        ],
    ).model_dump_json()

    async def _module_brd_side_effect(message: str, **kwargs) -> str:
        for mid in brd_canned:
            if f"`{mid}`" in message:
                return brd_canned[mid]
        return "## Business Rules\n- r\n## Error Paths\n- e\n## Side Effects\n- none\n"

    async def _module_design_side_effect(message: str, **kwargs) -> str:
        for mid in design_canned:
            if f"`{mid}`" in message:
                return design_canned[mid]
        return "## State Mapping\n- none\n"

    with patch("agent_harness.discovery.repo_scanner._run_agent",
               new=AsyncMock(return_value=inv_json)), \
         patch("agent_harness.discovery.dependency_grapher._run_agent",
               new=AsyncMock(return_value="[]")), \
         patch("agent_harness.discovery.brd_extractor._run_module_agent",
               side_effect=_module_brd_side_effect), \
         patch("agent_harness.discovery.brd_extractor._run_system_agent",
               new=AsyncMock(return_value="# System BRD\nok")), \
         patch("agent_harness.discovery.architect._run_module_agent",
               side_effect=_module_design_side_effect), \
         patch("agent_harness.discovery.architect._run_system_agent",
               new=AsyncMock(return_value="# System Design\nok")), \
         patch("agent_harness.discovery.story_decomposer._run_agent",
               new=AsyncMock(return_value=stories_canned)):
        result = await run_discovery(repo_id="synth", repo_path=str(FIXTURE), repo=repo)

    assert result["status"] == "ok"

    from agent_harness.discovery.tools.graph_io import load
    graph = load(paths.graph_path("synth"))
    edges = {(e.src, e.dst, e.kind) for e in graph.edges}
    assert ("orders", "dynamodb_table:Orders", "writes") in edges
    assert ("orders", "sqs_queue:payments-queue", "produces") in edges
    assert ("payments", "dynamodb_table:Payments", "writes") in edges
    assert ("payments", "sns_topic:payment-events", "produces") in edges
    assert ("notifications", "secrets_manager_secret:webhook/url", "reads") in edges
    assert not any(e[1] == "shared" for e in edges)

    backlog = await run_planning(repo_id="synth", repo=repo)
    waves = [item.wave for item in backlog.items]
    assert waves == sorted(waves)
    assert max(waves) - min(waves) == 2
    assert paths.backlog_path("synth").exists()


def test_synthesize_stories_fast_path_produces_module_level_dag():
    inventory = Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 3, "total_loc": 30,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py", loc=10, config_files=[]),
            ModuleRecord(id="payments", path="payments", language="python",
                         handler_entrypoint="payments/handler.py", loc=10, config_files=[]),
            ModuleRecord(id="notifications", path="notifications", language="python",
                         handler_entrypoint="notifications/handler.py", loc=10, config_files=[]),
        ],
    )
    from agent_harness.discovery.artifacts import DependencyGraph, GraphNode, GraphEdge
    graph = DependencyGraph(
        nodes=[
            GraphNode(id="orders", kind="module", attrs={}),
            GraphNode(id="payments", kind="module", attrs={}),
            GraphNode(id="notifications", kind="module", attrs={}),
        ],
        edges=[
            GraphEdge(src="payments", dst="orders", kind="imports"),
            GraphEdge(src="notifications", dst="payments", kind="imports"),
        ],
    )

    stories = synthesize_stories(inventory, graph)

    assert {epic.module_id for epic in stories.epics} == {"orders", "payments", "notifications"}
    by_id = {story.id: story for story in stories.stories}
    assert by_id["S-orders"].depends_on == []
    assert by_id["S-payments"].depends_on == ["S-orders"]
    assert by_id["S-notifications"].depends_on == ["S-payments"]
    assert all(story.acceptance_criteria for story in stories.stories)
