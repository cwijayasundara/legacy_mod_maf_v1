from pathlib import Path

from agent_harness.discovery.artifacts import (
    Stories, Story, Epic, AcceptanceCriterion, Inventory, ModuleRecord,
    DependencyGraph, GraphNode, GraphEdge,
)
from agent_harness.discovery.wave_scheduler import schedule


def _story(sid, mod="orders", deps=()):
    return Story(id=sid, epic_id="E-" + mod, title="t", description="d",
                 acceptance_criteria=[AcceptanceCriterion(text="ac")],
                 depends_on=list(deps), blocks=[], estimate="M")


def _stories(stories_by_mod: dict[str, list[Story]]) -> Stories:
    epics = [Epic(id=f"E-{m}", module_id=m, title="E",
                  story_ids=[s.id for s in sl])
             for m, sl in stories_by_mod.items()]
    flat = [s for sl in stories_by_mod.values() for s in sl]
    return Stories(epics=epics, stories=flat)


def test_source_paths_use_handler_entrypoint(tmp_path):
    (tmp_path / "orders").mkdir()
    (tmp_path / "orders" / "handler.py").write_text("def handler(e,c): pass\n")

    inv = Inventory(
        repo_meta={"root_path": str(tmp_path), "total_files": 1,
                   "total_loc": 1, "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path="orders", language="python",
                              handler_entrypoint="orders/handler.py",
                              loc=1, config_files=[])],
    )
    graph = DependencyGraph(nodes=[], edges=[])
    stories = _stories({"orders": [_story("S1", "orders")]})
    backlog = schedule(stories, language_by_module={"orders": "python"},
                       inventory=inv, graph=graph)
    assert len(backlog.items) == 1
    item = backlog.items[0]
    assert item.source_paths == [str(tmp_path / "orders" / "handler.py")]
    assert item.context_paths == []


def test_context_paths_include_shared_siblings(tmp_path):
    """Handler imports ..services → all *.py under services/ land in context_paths."""
    (tmp_path / "handlers").mkdir()
    (tmp_path / "handlers" / "orders.py").write_text("from ..services import x\n")
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "x.py").write_text("def x(): pass\n")
    (tmp_path / "services" / "y.py").write_text("def y(): pass\n")

    inv = Inventory(
        repo_meta={"root_path": str(tmp_path), "total_files": 3,
                   "total_loc": 3, "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path="handlers", language="python",
                              handler_entrypoint="handlers/orders.py",
                              loc=1, config_files=[])],
    )
    graph = DependencyGraph(
        nodes=[GraphNode(id="orders", kind="module", attrs={"path": "handlers"})],
        edges=[GraphEdge(src="orders", dst="services", kind="imports")],
    )
    stories = _stories({"orders": [_story("S1", "orders")]})
    backlog = schedule(stories, language_by_module={"orders": "python"},
                       inventory=inv, graph=graph)
    ctx = set(backlog.items[0].context_paths)
    assert str(tmp_path / "services" / "x.py") in ctx
    assert str(tmp_path / "services" / "y.py") in ctx


def test_context_skips_backlog_peer_module(tmp_path):
    """Imports between two modules both being migrated → NOT in context."""
    (tmp_path / "orders").mkdir()
    (tmp_path / "orders" / "handler.py").write_text("from payments import x\n")
    (tmp_path / "payments").mkdir()
    (tmp_path / "payments" / "handler.py").write_text("def x(): pass\n")

    inv = Inventory(
        repo_meta={"root_path": str(tmp_path), "total_files": 2,
                   "total_loc": 2, "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py", loc=1, config_files=[]),
            ModuleRecord(id="payments", path="payments", language="python",
                         handler_entrypoint="payments/handler.py", loc=1, config_files=[]),
        ],
    )
    graph = DependencyGraph(
        nodes=[GraphNode(id="orders", kind="module", attrs={"path": "orders"}),
               GraphNode(id="payments", kind="module", attrs={"path": "payments"})],
        edges=[GraphEdge(src="orders", dst="payments", kind="imports")],
    )
    stories = _stories({
        "orders": [_story("S1", "orders", deps=["S2"])],
        "payments": [_story("S2", "payments")],
    })
    backlog = schedule(stories, language_by_module={"orders": "python", "payments": "python"},
                       inventory=inv, graph=graph)
    orders_item = next(i for i in backlog.items if i.module == "orders")
    assert orders_item.context_paths == []


def test_source_paths_default_when_no_inventory_match():
    """Edge case: a story whose module is not in the inventory (shouldn't happen,
    but we don't want to crash)."""
    from agent_harness.discovery.artifacts import Inventory, DependencyGraph
    inv = Inventory(
        repo_meta={"root_path": "/nope", "total_files": 0, "total_loc": 0,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[],
    )
    graph = DependencyGraph(nodes=[], edges=[])
    stories = _stories({"ghost": [_story("S1", "ghost")]})
    backlog = schedule(stories, language_by_module={"ghost": "python"},
                       inventory=inv, graph=graph)
    assert backlog.items[0].source_paths == []
    assert backlog.items[0].context_paths == []
