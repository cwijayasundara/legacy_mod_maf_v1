import json
from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, DependencyGraph, GraphNode, GraphEdge,
    ModuleBRD, SystemBRD, ModuleDesign, SystemDesign,
    Epic, Story, AcceptanceCriterion, Stories,
    BacklogItem, Backlog, CriticReport,
)


def test_inventory_round_trip():
    inv = Inventory(
        repo_meta={"root_path": "/r", "total_files": 3, "total_loc": 100,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="src/lambda/orders", language="python",
                         handler_entrypoint="src/lambda/orders/handler.py",
                         loc=42, config_files=["src/lambda/orders/requirements.txt"])
        ],
    )
    raw = inv.model_dump_json()
    again = Inventory.model_validate_json(raw)
    assert again == inv


def test_graph_round_trip():
    g = DependencyGraph(
        nodes=[GraphNode(id="orders", kind="module", attrs={}),
               GraphNode(id="orders-table", kind="aws_resource",
                         attrs={"resource_kind": "dynamodb_table"})],
        edges=[GraphEdge(src="orders", dst="orders-table", kind="reads")],
    )
    again = DependencyGraph.model_validate_json(g.model_dump_json())
    assert again == g


def test_backlog_item_is_superset_of_migrate_request():
    """BacklogItem must be JSON-compatible with the existing /migrate endpoint."""
    from agent_harness.orchestrator.api import MigrationRequest
    item = BacklogItem(
        module="orders", language="python", work_item_id="WI-1",
        title="Migrate orders", description="...", acceptance_criteria="...",
        wave=1,
    )
    payload = json.loads(item.model_dump_json())
    payload.pop("wave")
    MigrationRequest.model_validate(payload)  # must not raise


def test_critic_report_pass_fail():
    r = CriticReport(verdict="PASS", reasons=[], suggestions=[])
    assert r.verdict == "PASS"
    r2 = CriticReport(verdict="FAIL", reasons=["missing edge x→y"], suggestions=["add edge"])
    assert r2.verdict == "FAIL"
    assert "missing" in r2.reasons[0]


def test_story_dependencies():
    s = Story(id="S1", epic_id="E1", title="t", description="d",
              acceptance_criteria=[AcceptanceCriterion(text="a")],
              depends_on=["S0"], blocks=[], estimate="M")
    assert s.depends_on == ["S0"]
