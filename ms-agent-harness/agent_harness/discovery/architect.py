"""Architect agent — produces target Azure design markdown."""
from __future__ import annotations

import asyncio
import logging
import os

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import (
    DependencyGraph, Inventory, ModuleBRD, ModuleDesign, SystemBRD, SystemDesign,
)
from . import paths

logger = logging.getLogger("discovery.architect")

DEFAULT_CONCURRENCY = 4


async def _run_module_agent(message: str, repo_root: str | None = None) -> str:
    agent = create_agent(role="architect",
                         tools=[read_file, list_directory, search_files],
                         repo_root=repo_root)
    return await run_with_retry(agent, message)


async def _run_system_agent(message: str, repo_root: str | None = None) -> str:
    agent = create_agent(role="architect",
                         tools=[read_file, list_directory, search_files],
                         repo_root=repo_root)
    return await run_with_retry(agent, message)


async def design(repo_id: str, inventory: Inventory, graph: DependencyGraph,
                 module_brds: list[ModuleBRD], system_brd: SystemBRD,
                 extra_instructions: str = "",
                 repo_root: str | None = None) -> tuple[list[ModuleDesign], SystemDesign]:
    _repo_root = str(repo_root) if repo_root else None
    by_id = {b.module_id: b for b in module_brds}
    max_concurrency = max(
        1,
        int(os.environ.get("DISCOVERY_ARCHITECT_CONCURRENCY", str(DEFAULT_CONCURRENCY))),
    )
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _design_module(module_id: str, brd_body: str, edges_text: str) -> ModuleDesign:
        async with semaphore:
            logger.info("[architect] designing module %s", module_id)
            msg = (
                f"Produce the Azure target design markdown for module `{module_id}`.\n\n"
                f"## Required sections (## headings):\n"
                f"- Function Plan (Consumption/Premium/Flex)\n"
                f"- Trigger Bindings (one entry per source AWS trigger)\n"
                f"- State Mapping (one entry per AWS resource the module touches)\n"
                f"- Secrets\n- Identity\n- IaC (Bicep)\n- Observability\n\n"
                f"## Module BRD\n{brd_body}\n\n"
                f"## Module edges\n{edges_text}"
                f"\n\n{extra_instructions}\n\nOutput ONLY the markdown body."
            )
            body = await _run_module_agent(msg, repo_root=_repo_root)
            out = paths.module_design_path(repo_id, module_id)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body, encoding="utf-8")
            logger.info("[architect] module %s complete", module_id)
            return ModuleDesign(module_id=module_id, body=body)

    module_jobs: list[tuple[str, asyncio.Task[ModuleDesign]]] = []

    for m in inventory.modules:
        brd = by_id.get(m.id)
        if brd is None:
            continue
        edges = [e for e in graph.edges if e.src == m.id or e.dst == m.id]
        edges_text = "\n".join(f"- {e.src} -[{e.kind}]-> {e.dst}" for e in edges)
        module_jobs.append(
            (
                m.id,
                asyncio.create_task(_design_module(m.id, brd.body, edges_text)),
            )
        )

    sys_msg = (
        "Produce `_system.md` covering Strangler Seams, Anti-Corruption Layers, "
        "and Shared Resource Migration Ordering.\n\n"
        f"## System BRD\n{system_brd.body}\n\nOutput ONLY the markdown body."
    )
    logger.info("[architect] designing system view")
    sys_task = asyncio.create_task(_run_system_agent(sys_msg, repo_root=_repo_root))

    design_results = await asyncio.gather(*(task for _, task in module_jobs))
    designs_by_id = {design.module_id: design for design in design_results}
    designs = [designs_by_id[m.id] for m in inventory.modules if m.id in designs_by_id]

    sys_body = await sys_task
    sys_path = paths.system_design_path(repo_id)
    sys_path.parent.mkdir(parents=True, exist_ok=True)
    sys_path.write_text(sys_body, encoding="utf-8")
    logger.info("[architect] system view complete")
    return designs, SystemDesign(body=sys_body)
