from agent_harness.discovery.artifacts import DependencyGraph, GraphNode, GraphEdge
from agent_harness.eval.scorers.graph import score


def _graph(nodes, edges):
    return DependencyGraph(
        nodes=[GraphNode(id=n[0], kind=n[1], attrs=n[2] if len(n) > 2 else {})
               for n in nodes],
        edges=[GraphEdge(src=e[0], dst=e[1], kind=e[2]) for e in edges],
    )


def test_identical_graphs_score_one():
    g = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource",
          {"resource_kind": "dynamodb_table"})],
        [("orders", "dynamodb_table:Orders", "writes")],
    )
    r = score(g, g)
    assert r.stage == "graph"
    assert r.score == 1.0
    assert r.passed is True


def test_missing_edge_drops_score_below_threshold():
    got = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource", {})],
        [],
    )
    expected = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource", {})],
        [("orders", "dynamodb_table:Orders", "writes")],
    )
    r = score(got, expected)
    assert r.score < r.threshold
    assert r.passed is False
    assert ["orders", "dynamodb_table:Orders", "writes"] in [
        list(e) for e in r.details["missing_edges"]
    ]


def test_missing_aws_resource_node_fails():
    got = _graph([("orders", "module", {})], [])
    expected = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource", {})],
        [],
    )
    r = score(got, expected)
    assert r.passed is False
    assert "dynamodb_table:Orders" in r.details["missing_resources"]


def test_extra_edges_counted_but_tolerated_up_to_threshold():
    got = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource", {}),
         ("sqs_queue:q", "aws_resource", {})],
        [("orders", "dynamodb_table:Orders", "writes"),
         ("orders", "sqs_queue:q", "produces"),
         ("orders", "sqs_queue:q", "produces")],
    )
    expected = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource", {})],
        [("orders", "dynamodb_table:Orders", "writes")],
    )
    r = score(got, expected)
    assert r.score < r.threshold
    assert len(r.details["extra_edges"]) == 1


def test_threshold_is_0_9():
    g = _graph([], [])
    r = score(g, g)
    assert r.threshold == 0.9
