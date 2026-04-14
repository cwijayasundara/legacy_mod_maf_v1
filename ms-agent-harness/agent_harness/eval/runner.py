"""Run the discovery pipeline against a corpus under a chosen tier."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, patch

from ..discovery import paths as discovery_paths
from ..discovery.artifacts import DependencyGraph, Inventory, Stories
from ..discovery.workflow import run_discovery
from ..persistence.repository import MigrationRepository
from .corpus import Corpus

Tier = Literal["deterministic", "real_llm"]


@dataclass
class RunArtifacts:
    inventory: Inventory
    graph: DependencyGraph
    brd: dict[str, str]
    design: dict[str, str]
    stories: Stories
    run_dir: Path


async def run_corpus(corpus: Corpus, tier: Tier,
                     repo: MigrationRepository,
                     repo_id: str | None = None) -> RunArtifacts:
    if tier not in ("deterministic", "real_llm"):
        raise ValueError(f"unknown tier: {tier!r}")

    repo_id = repo_id or f"eval-{corpus.name}"
    if tier == "real_llm":
        await run_discovery(repo_id=repo_id, repo_path=str(corpus.repo_path),
                            repo=repo)
    else:
        canned = _load_canned(corpus)
        with patch("agent_harness.discovery.repo_scanner._run_agent",
                   new=AsyncMock(return_value=canned["inventory"])), \
             patch("agent_harness.discovery.dependency_grapher._run_agent",
                   new=AsyncMock(return_value=canned["graph"])), \
             patch("agent_harness.discovery.brd_extractor._run_module_agent",
                   side_effect=_module_side_effect(canned["brd"])), \
             patch("agent_harness.discovery.brd_extractor._run_system_agent",
                   new=AsyncMock(return_value=canned["system_brd"])), \
             patch("agent_harness.discovery.architect._run_module_agent",
                   side_effect=_module_side_effect(canned["design"])), \
             patch("agent_harness.discovery.architect._run_system_agent",
                   new=AsyncMock(return_value=canned["system_design"])), \
             patch("agent_harness.discovery.story_decomposer._run_agent",
                   new=AsyncMock(return_value=canned["stories"])):
            await run_discovery(repo_id=repo_id, repo_path=str(corpus.repo_path),
                                repo=repo)

    # Load artifacts back from disk.
    inv = Inventory.model_validate_json(
        discovery_paths.inventory_path(repo_id).read_text(encoding="utf-8")
    )
    graph = DependencyGraph.model_validate_json(
        discovery_paths.graph_path(repo_id).read_text(encoding="utf-8")
    )
    brd_dir = discovery_paths.brd_dir(repo_id)
    brd = {p.stem: p.read_text(encoding="utf-8") for p in brd_dir.glob("*.md")
           if not p.stem.startswith("_")}
    design_dir = discovery_paths.design_dir(repo_id)
    design = {p.stem: p.read_text(encoding="utf-8") for p in design_dir.glob("*.md")
              if not p.stem.startswith("_")}
    stories = Stories.model_validate_json(
        discovery_paths.stories_path(repo_id).read_text(encoding="utf-8")
    )
    return RunArtifacts(
        inventory=inv, graph=graph, brd=brd, design=design,
        stories=stories, run_dir=discovery_paths.repo_dir(repo_id),
    )


def _load_canned(corpus: Corpus) -> dict:
    base = corpus.canned_dir
    brd = {p.stem[len("brd_"):]: p.read_text(encoding="utf-8")
           for p in base.glob("brd_*.md")}
    design = {p.stem[len("design_"):]: p.read_text(encoding="utf-8")
              for p in base.glob("design_*.md")}
    return {
        "inventory":     (base / "inventory.json").read_text(encoding="utf-8"),
        "graph":         (base / "graph.json").read_text(encoding="utf-8"),
        "brd":           brd,
        "system_brd":    (base / "system_brd.md").read_text(encoding="utf-8"),
        "design":        design,
        "system_design": (base / "system_design.md").read_text(encoding="utf-8"),
        "stories":       (base / "stories.json").read_text(encoding="utf-8"),
    }


def _module_side_effect(per_module: dict[str, str]):
    async def _fn(message: str) -> str:
        for mid, body in per_module.items():
            if f"`{mid}`" in message:
                return body
        return next(iter(per_module.values()))
    return _fn
