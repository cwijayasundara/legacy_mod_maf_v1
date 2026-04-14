"""StoryDecomposer agent — turns BRDs+designs into epics and stories."""
from __future__ import annotations

import logging

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import (
    DependencyGraph, Inventory, ModuleBRD, ModuleDesign, Stories, SystemBRD, SystemDesign,
)
from . import paths

logger = logging.getLogger("discovery.stories")


async def _run_agent(message: str, repo_root: str | None = None) -> str:
    agent = create_agent(role="story_decomposer",
                         tools=[read_file, list_directory, search_files],
                         repo_root=repo_root)
    return await run_with_retry(agent, message)


async def decompose(repo_id: str, inventory: Inventory, graph: DependencyGraph,
                    module_brds: list[ModuleBRD], system_brd: SystemBRD,
                    module_designs: list[ModuleDesign], system_design: SystemDesign,
                    extra_instructions: str = "",
                    repo_root: str | None = None) -> Stories:
    msg = (
        "Decompose the migration into epics and stories. Return ONLY a JSON object "
        "matching the Stories schema with keys: epics, stories.\n\n"
        f"## Inventory modules\n{', '.join(m.id for m in inventory.modules)}\n\n"
        f"## System BRD\n{system_brd.body}\n\n"
        f"## System Design\n{system_design.body}\n\n"
        f"## Per-module BRDs\n" + "\n\n".join(f"### {b.module_id}\n{b.body}" for b in module_brds) + "\n\n"
        f"## Per-module Designs\n" + "\n\n".join(f"### {d.module_id}\n{d.body}" for d in module_designs) + "\n\n"
        f"## Resource edges\n" + "\n".join(f"- {e.src} -[{e.kind}]-> {e.dst}" for e in graph.edges) + "\n\n"
        f"{extra_instructions}\n\n"
        "Rules:\n"
        "- At least one epic per module.\n"
        "- Every story has at least one acceptance_criteria entry.\n"
        "- depends_on must reference story ids that exist in this output.\n"
        "- The dependency subgraph must be acyclic.\n"
    )
    raw = await _run_agent(msg, repo_root=str(repo_root) if repo_root else None)
    stories = Stories.model_validate_json(_strip_fences(raw))
    out = paths.stories_path(repo_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(stories.model_dump_json(indent=2), encoding="utf-8")
    return stories


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
