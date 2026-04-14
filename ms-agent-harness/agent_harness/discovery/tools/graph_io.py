"""Build, serialize, and load a DependencyGraph."""
from __future__ import annotations

import uuid
from pathlib import Path

from ..artifacts import DependencyGraph, GraphEdge, GraphNode


class GraphBuilder:
    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: set[tuple[str, str, str]] = set()

    def add_module(self, module_id: str, attrs: dict | None = None) -> str:
        if module_id not in self._nodes:
            self._nodes[module_id] = GraphNode(
                id=module_id, kind="module", attrs=attrs or {},
            )
        return module_id

    def add_resource(self, kind: str, name: str | None, attrs: dict | None = None) -> str:
        node_id = f"{kind}:{name}" if name else f"{kind}:<unknown:{uuid.uuid4().hex[:8]}>"
        if node_id not in self._nodes:
            merged = {"resource_kind": kind, **(attrs or {})}
            if name:
                merged["resource_name"] = name
            self._nodes[node_id] = GraphNode(id=node_id, kind="aws_resource", attrs=merged)
        return node_id

    def add_edge(self, src: str, dst: str, kind: str) -> None:
        self._edges.add((src, dst, kind))

    def build(self) -> DependencyGraph:
        return DependencyGraph(
            nodes=list(self._nodes.values()),
            edges=[GraphEdge(src=s, dst=d, kind=k) for (s, d, k) in sorted(self._edges)],
        )


def save(graph: DependencyGraph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(graph.model_dump_json(indent=2), encoding="utf-8")


def load(path: Path) -> DependencyGraph:
    return DependencyGraph.model_validate_json(Path(path).read_text(encoding="utf-8"))
