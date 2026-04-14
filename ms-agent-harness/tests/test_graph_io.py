import json
from pathlib import Path
from agent_harness.discovery.artifacts import DependencyGraph
from agent_harness.discovery.tools.graph_io import GraphBuilder, save, load


def test_builder_dedupes_nodes_and_edges():
    b = GraphBuilder()
    b.add_module("orders")
    b.add_module("orders")  # duplicate
    b.add_resource("dynamodb_table", "Orders")
    b.add_resource("dynamodb_table", "Orders")  # duplicate
    b.add_edge("orders", "dynamodb_table:Orders", "writes")
    b.add_edge("orders", "dynamodb_table:Orders", "writes")  # duplicate
    g = b.build()
    assert len(g.nodes) == 2
    assert len(g.edges) == 1


def test_resource_id_includes_kind():
    b = GraphBuilder()
    b.add_resource("s3_bucket", "logs")
    g = b.build()
    assert g.nodes[0].id == "s3_bucket:logs"
    assert g.nodes[0].attrs["resource_kind"] == "s3_bucket"


def test_resource_without_name_uses_unknown(tmp_path):
    b = GraphBuilder()
    b.add_resource("s3_bucket", None)
    g = b.build()
    assert g.nodes[0].id.startswith("s3_bucket:<unknown:")


def test_save_and_load_round_trip(tmp_path):
    b = GraphBuilder()
    b.add_module("a")
    b.add_module("b")
    b.add_edge("a", "b", "imports")
    g = b.build()
    p = tmp_path / "g.json"
    save(g, p)
    again = load(p)
    assert again == g
