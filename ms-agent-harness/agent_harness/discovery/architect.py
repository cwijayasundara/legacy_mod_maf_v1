"""Architect agent — produces target Azure design markdown."""
from __future__ import annotations

import logging

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import (
    DependencyGraph, Inventory, ModuleBRD, ModuleDesign, SystemBRD, SystemDesign,
)
from . import paths

logger = logging.getLogger("discovery.architect")


async def _run_module_agent(message: str) -> str:
    agent = create_agent(role="architect",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def _run_system_agent(message: str) -> str:
    agent = create_agent(role="architect",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def design(repo_id: str, inventory: Inventory, graph: DependencyGraph,
                 module_brds: list[ModuleBRD], system_brd: SystemBRD,
                 extra_instructions: str = "") -> tuple[list[ModuleDesign], SystemDesign]:
    designs: list[ModuleDesign] = []
    by_id = {b.module_id: b for b in module_brds}

    for m in inventory.modules:
        brd = by_id.get(m.id)
        if brd is None:
            continue
        edges = [e for e in graph.edges if e.src == m.id or e.dst == m.id]
        msg = (
            f"Produce the Azure target design markdown for module `{m.id}`.\n\n"
            f"## Required sections (## headings):\n"
            f"- Function Plan (Consumption/Premium/Flex)\n"
            f"- Trigger Bindings (one entry per source AWS trigger)\n"
            f"- State Mapping (one entry per AWS resource the module touches)\n"
            f"- Secrets\n- Identity\n- IaC (Bicep)\n- Observability\n\n"
            f"## Module BRD\n{brd.body}\n\n"
            f"## Module edges\n" + "\n".join(f"- {e.src} -[{e.kind}]-> {e.dst}" for e in edges)
            + f"\n\n{extra_instructions}\n\nOutput ONLY the markdown body."
        )
        body = await _run_module_agent(msg)
        d = ModuleDesign(module_id=m.id, body=body)
        out = paths.module_design_path(repo_id, m.id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
        designs.append(d)

    sys_msg = (
        "Produce `_system.md` covering Strangler Seams, Anti-Corruption Layers, "
        "and Shared Resource Migration Ordering.\n\n"
        f"## System BRD\n{system_brd.body}\n\nOutput ONLY the markdown body."
    )
    sys_body = await _run_system_agent(sys_msg)
    paths.system_design_path(repo_id).write_text(sys_body, encoding="utf-8")
    return designs, SystemDesign(body=sys_body)
