"""Corpus loader — reads tests/eval_corpus/<name>/*."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..discovery.artifacts import DependencyGraph, Inventory

CORPUS_ROOT = Path(__file__).parent.parent.parent / "tests" / "eval_corpus"


@dataclass
class Corpus:
    name: str
    repo_path: Path
    expected_inventory: Inventory
    expected_graph: DependencyGraph
    expected_stories: dict[str, Any]
    canned_dir: Path


def load_corpus(name: str) -> Corpus:
    base = CORPUS_ROOT / name
    if not base.is_dir():
        raise FileNotFoundError(f"corpus {name!r} not found under {CORPUS_ROOT}")

    meta = yaml.safe_load((base / "corpus.yaml").read_text(encoding="utf-8"))
    repo_path = (base / meta["repo_path"]).resolve()

    inv = Inventory.model_validate_json(
        (base / "expected_inventory.json").read_text(encoding="utf-8")
    )
    graph = DependencyGraph.model_validate_json(
        (base / "expected_graph.json").read_text(encoding="utf-8")
    )
    stories = json.loads(
        (base / "expected_stories_shape.json").read_text(encoding="utf-8")
    )
    return Corpus(
        name=meta["name"], repo_path=repo_path,
        expected_inventory=inv, expected_graph=graph,
        expected_stories=stories, canned_dir=base / "canned",
    )
