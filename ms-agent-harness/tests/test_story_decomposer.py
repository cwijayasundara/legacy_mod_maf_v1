from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, DependencyGraph,
    ModuleBRD, SystemBRD, ModuleDesign, SystemDesign, Stories, Story,
    Epic, AcceptanceCriterion,
)
from agent_harness.discovery.story_decomposer import decompose
from agent_harness.discovery.critics.story_critic import critique_stories
from agent_harness.discovery import paths


def _inv():
    return Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py", loc=10, config_files=[]),
            ModuleRecord(id="payments", path="payments", language="python",
                         handler_entrypoint="payments/handler.py", loc=10, config_files=[]),
        ],
    )


@pytest.mark.asyncio
async def test_decompose_writes_stories(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    canned = Stories(
        epics=[
            Epic(id="E1", module_id="orders", title="Migrate orders", story_ids=["S1"]),
            Epic(id="E2", module_id="payments", title="Migrate payments", story_ids=["S2"]),
        ],
        stories=[
            Story(id="S1", epic_id="E1", title="HTTP function",
                  description="d", acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=[], blocks=[], estimate="M"),
            Story(id="S2", epic_id="E2", title="SQS consumer",
                  description="d", acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S1"], blocks=[], estimate="M"),
        ],
    ).model_dump_json()

    with patch("agent_harness.discovery.story_decomposer._run_agent",
               new=AsyncMock(return_value=canned)):
        stories = await decompose(
            repo_id="synth",
            inventory=_inv(),
            graph=DependencyGraph(nodes=[], edges=[]),
            module_brds=[ModuleBRD(module_id="orders", body=""),
                         ModuleBRD(module_id="payments", body="")],
            system_brd=SystemBRD(body=""),
            module_designs=[ModuleDesign(module_id="orders", body=""),
                            ModuleDesign(module_id="payments", body="")],
            system_design=SystemDesign(body=""),
        )

    assert paths.stories_path("synth").exists()
    assert {e.id for e in stories.epics} == {"E1", "E2"}


def test_story_critic_passes_on_valid_stories():
    s = Stories(
        epics=[Epic(id="E1", module_id="orders", title="t", story_ids=["S1"])],
        stories=[Story(id="S1", epic_id="E1", title="t", description="d",
                       acceptance_criteria=[AcceptanceCriterion(text="ac")],
                       depends_on=[], blocks=[], estimate="M")],
    )
    inv = Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path=".", language="python",
                              handler_entrypoint=".", loc=1, config_files=[])],
    )
    report = critique_stories(s, inv)
    assert report.verdict == "PASS"


def test_story_critic_fails_on_unknown_dep():
    s = Stories(
        epics=[Epic(id="E1", module_id="orders", title="t", story_ids=["S1"])],
        stories=[Story(id="S1", epic_id="E1", title="t", description="d",
                       acceptance_criteria=[AcceptanceCriterion(text="ac")],
                       depends_on=["GHOST"], blocks=[], estimate="M")],
    )
    inv = Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path=".", language="python",
                              handler_entrypoint=".", loc=1, config_files=[])],
    )
    report = critique_stories(s, inv)
    assert report.verdict == "FAIL"
    assert any("GHOST" in r for r in report.reasons)


def test_story_critic_fails_on_cycle():
    s = Stories(
        epics=[Epic(id="E1", module_id="orders", title="t", story_ids=["S1", "S2"])],
        stories=[
            Story(id="S1", epic_id="E1", title="t", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S2"], blocks=[], estimate="M"),
            Story(id="S2", epic_id="E1", title="t", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S1"], blocks=[], estimate="M"),
        ],
    )
    inv = Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path=".", language="python",
                              handler_entrypoint=".", loc=1, config_files=[])],
    )
    report = critique_stories(s, inv)
    assert report.verdict == "FAIL"
    assert any("cycle" in r.lower() for r in report.reasons)


def test_story_critic_fails_when_module_has_no_epic():
    s = Stories(epics=[], stories=[])
    inv = Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path=".", language="python",
                              handler_entrypoint=".", loc=1, config_files=[])],
    )
    report = critique_stories(s, inv)
    assert report.verdict == "FAIL"
    assert any("orders" in r for r in report.reasons)
