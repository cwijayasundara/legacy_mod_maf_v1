"""StoryDecomposer agent — turns BRDs+designs into epics and stories."""
from __future__ import annotations

import logging
import os

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import (
    AcceptanceCriterion, DependencyGraph, Epic, Inventory, ModuleBRD, ModuleDesign, Story,
    Stories, SystemBRD, SystemDesign,
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
    if os.environ.get("DISCOVERY_FAST_STORIES") == "1":
        logger.info("[stories] using deterministic fast-path")
        stories = synthesize_stories(inventory, graph)
        out = paths.stories_path(repo_id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(stories.model_dump_json(indent=2), encoding="utf-8")
        return stories

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


def synthesize_stories(inventory: Inventory, graph: DependencyGraph) -> Stories:
    """Generate a deterministic module-level migration backlog.

    Fast-path for small/straightforward repos where one migration story per
    module is sufficient and avoids a large synthesis LLM call.
    """
    module_ids = [m.id for m in inventory.modules]
    module_set = set(module_ids)
    raw_deps: dict[str, set[str]] = {m.id: set() for m in inventory.modules}
    for edge in graph.edges:
        if edge.src in module_set and edge.dst in module_set and edge.src != edge.dst:
            raw_deps[edge.src].add(edge.dst)

    deps = _break_cycles(raw_deps, module_ids)
    epics: list[Epic] = []
    stories: list[Story] = []

    for module in inventory.modules:
        epic_id = f"E-{module.id}"
        story_id = f"S-{module.id}"
        dep_story_ids = [f"S-{dep}" for dep in sorted(deps.get(module.id, set()))]
        title = f"Migrate {module.id}"
        description = (
            f"Migrate handler `{module.handler_entrypoint}` from AWS Lambda to Azure Functions "
            f"and preserve its source behavior."
        )
        acceptance = [
            AcceptanceCriterion(text=f"Azure Function for `{module.id}` is generated from `{module.handler_entrypoint}`."),
            AcceptanceCriterion(text=f"Tests and infrastructure for `{module.id}` are generated."),
            AcceptanceCriterion(text=f"Behavioral contract for `{module.id}` is preserved relative to the source handler."),
        ]
        epics.append(Epic(id=epic_id, module_id=module.id, title=title, story_ids=[story_id]))
        stories.append(
            Story(
                id=story_id,
                epic_id=epic_id,
                title=title,
                description=description,
                acceptance_criteria=acceptance,
                depends_on=dep_story_ids,
                blocks=[],
                estimate="M",
            )
        )
    return Stories(epics=epics, stories=stories)


def _break_cycles(raw_deps: dict[str, set[str]], module_order: list[str]) -> dict[str, set[str]]:
    """Keep only dependency edges that preserve an acyclic module order."""
    kept: dict[str, set[str]] = {module: set() for module in module_order}
    position = {module: idx for idx, module in enumerate(module_order)}
    for module in module_order:
        for dep in sorted(raw_deps.get(module, set()), key=lambda item: position.get(item, 10**9)):
            if dep not in position:
                continue
            if _reachable(dep, module, kept):
                continue
            kept[module].add(dep)
    return kept


def _reachable(start: str, target: str, deps: dict[str, set[str]]) -> bool:
    stack = [start]
    seen: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur == target:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(deps.get(cur, set()))
    return False


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
