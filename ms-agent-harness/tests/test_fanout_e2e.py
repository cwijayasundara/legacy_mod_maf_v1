"""Discover → plan → approve → migrate-repo/sync against the synthetic fixture."""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, Stories, Story, Epic, AcceptanceCriterion,
)
from agent_harness.discovery import paths as discovery_paths
from agent_harness.discovery.workflow import run_discovery, run_planning
from agent_harness.fanout import migrate_repo
from agent_harness.persistence.repository import MigrationRepository
from agent_harness.pipeline import PipelineResult

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


def _brd_body(refs: list[str]) -> str:
    side = "\n".join(f"- writes/reads {r}" for r in refs)
    return (
        "## Purpose\nx\n\n## Triggers\nx\n\n## Inputs\nx\n\n## Outputs\nx\n\n"
        "## Business Rules\n- r\n\n"
        f"## Side Effects\n{side}\n\n"
        "## Error Paths\n- e\n\n## Non-Functionals\n- n\n\n## PII/Compliance\n- n\n"
    )


def _design_body(refs: list[str]) -> str:
    sm = "\n".join(f"- {r} → Azure target" for r in refs)
    return (
        "## Function Plan\nFlex\n\n## Trigger Bindings\n- HTTP\n\n"
        f"## State Mapping\n{sm}\n\n## Secrets\n- KV\n\n"
        "## Identity\n- MI\n\n## IaC\n- Bicep\n\n## Observability\n- AI\n"
    )


@pytest.mark.asyncio
async def test_discover_plan_approve_migrate_repo_e2e(tmp_path, monkeypatch):
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

    brd_canned = {
        "orders": _brd_body(["dynamodb_table:Orders", "sqs_queue:payments-queue"]),
        "payments": _brd_body(["dynamodb_table:Orders", "dynamodb_table:Payments",
                               "sns_topic:payment-events"]),
        "notifications": _brd_body(["secrets_manager_secret:webhook/url"]),
    }
    design_canned = {
        "orders": _design_body(["dynamodb_table:Orders", "sqs_queue:payments-queue"]),
        "payments": _design_body(["dynamodb_table:Orders", "dynamodb_table:Payments",
                                  "sns_topic:payment-events"]),
        "notifications": _design_body(["secrets_manager_secret:webhook/url"]),
    }
    stories_canned = Stories(
        epics=[Epic(id="E1", module_id="orders", title="o", story_ids=["S1"]),
               Epic(id="E2", module_id="payments", title="p", story_ids=["S2"]),
               Epic(id="E3", module_id="notifications", title="n", story_ids=["S3"])],
        stories=[
            Story(id="S1", epic_id="E1", title="o", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=[], blocks=[], estimate="M"),
            Story(id="S2", epic_id="E2", title="p", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S1"], blocks=[], estimate="M"),
            Story(id="S3", epic_id="E3", title="n", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S2"], blocks=[], estimate="M"),
        ],
    ).model_dump_json()

    async def _brd_side(message):
        for mid, body in brd_canned.items():
            if f"`{mid}`" in message:
                return body
        return "## Business Rules\n- r\n## Error Paths\n- e\n## Side Effects\n- none\n"

    async def _design_side(message):
        for mid, body in design_canned.items():
            if f"`{mid}`" in message:
                return body
        return "## State Mapping\n- none\n"

    with patch("agent_harness.discovery.repo_scanner._run_agent",
               new=AsyncMock(return_value=inv_json)), \
         patch("agent_harness.discovery.dependency_grapher._run_agent",
               new=AsyncMock(return_value="[]")), \
         patch("agent_harness.discovery.brd_extractor._run_module_agent",
               side_effect=_brd_side), \
         patch("agent_harness.discovery.brd_extractor._run_system_agent",
               new=AsyncMock(return_value="# System BRD\nok")), \
         patch("agent_harness.discovery.architect._run_module_agent",
               side_effect=_design_side), \
         patch("agent_harness.discovery.architect._run_system_agent",
               new=AsyncMock(return_value="# System Design\nok")), \
         patch("agent_harness.discovery.story_decomposer._run_agent",
               new=AsyncMock(return_value=stories_canned)):
        await run_discovery(repo_id="synth", repo_path=str(FIXTURE), repo=repo)

    backlog = await run_planning(repo_id="synth", repo=repo)
    for item in backlog.items:
        assert item.source_paths, f"source_paths empty for {item.module}"
        assert str(FIXTURE) in item.source_paths[0]

    repo.approve_backlog("synth", approver="tester")

    pipeline = AsyncMock()
    pipeline.run = AsyncMock(side_effect=lambda module, **kw: PipelineResult(
        module=module, status="completed", message="", review_score=85,
    ))

    result = await migrate_repo(repo_id="synth", repo=repo, pipeline=pipeline)
    assert result.status == "completed"
    by_mod = {m.module: m for m in result.modules}
    assert set(by_mod) == {"orders", "payments", "notifications"}
    assert all(m.status == "completed" for m in result.modules)
    assert pipeline.run.await_count == 3

    for call in pipeline.run.await_args_list:
        assert call.kwargs["source_paths"], \
            f"pipeline.run called without source_paths for {call.kwargs['module']}"
