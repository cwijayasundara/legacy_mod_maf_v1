"""Grapher-stage scorer — Jaccard over edge triples + resource-node coverage."""
from __future__ import annotations

from ...discovery.artifacts import DependencyGraph
from .base import ScoreResult

THRESHOLD = 0.9


def score(got: DependencyGraph, expected: DependencyGraph) -> ScoreResult:
    got_edges = {(e.src, e.dst, e.kind) for e in got.edges}
    expected_edges = {(e.src, e.dst, e.kind) for e in expected.edges}
    inter = got_edges & expected_edges
    union = got_edges | expected_edges
    edge_score = 1.0 if not union else len(inter) / len(union)

    expected_resources = {n.id for n in expected.nodes if n.kind == "aws_resource"}
    got_resources = {n.id for n in got.nodes if n.kind == "aws_resource"}
    missing_resources = sorted(expected_resources - got_resources)

    missing_edges = [list(e) for e in sorted(expected_edges - got_edges)]
    extra_edges = [list(e) for e in sorted(got_edges - expected_edges)]

    s = edge_score
    if expected_resources:
        res_score = len(got_resources & expected_resources) / len(expected_resources)
        s = (edge_score + res_score) / 2

    passed = (not missing_resources) and (not missing_edges) and (not extra_edges)
    if not passed and s >= THRESHOLD and not missing_resources and not missing_edges:
        passed = True

    return ScoreResult(
        stage="graph", score=s, passed=passed, threshold=THRESHOLD,
        details={
            "missing_edges": missing_edges,
            "extra_edges": extra_edges,
            "missing_resources": missing_resources,
        },
    )
