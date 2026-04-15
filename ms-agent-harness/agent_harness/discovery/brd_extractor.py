"""BRDExtractor — produces per-module + system BRD markdown."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import DependencyGraph, Inventory, ModuleBRD, SystemBRD
from . import paths

logger = logging.getLogger("discovery.brd")

DEFAULT_CONCURRENCY = 4


async def _run_module_agent(message: str, repo_root: str | None = None) -> str:
    agent = create_agent(role="brd_extractor",
                         tools=[read_file, list_directory, search_files],
                         repo_root=repo_root)
    return await run_with_retry(agent, message)


async def _run_system_agent(message: str, repo_root: str | None = None) -> str:
    agent = create_agent(role="brd_extractor",
                         tools=[read_file, list_directory, search_files],
                         repo_root=repo_root)
    return await run_with_retry(agent, message)


async def extract_brds(repo_id: str, repo_root: Path,
                       inventory: Inventory, graph: DependencyGraph,
                       extra_instructions: str = "") -> tuple[list[ModuleBRD], SystemBRD]:
    repo_root = Path(repo_root).resolve()
    max_concurrency = max(
        1,
        int(os.environ.get("DISCOVERY_BRD_CONCURRENCY", str(DEFAULT_CONCURRENCY))),
    )
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _extract_module(module_id: str, module_path: Path, edges_text: str) -> ModuleBRD:
        async with semaphore:
            logger.info("[brd] extracting module %s", module_id)
            sources = _collect_sources(module_path)
            msg = (
                f"Write a BRD markdown for module `{module_id}`.\n\n"
                f"Required sections: Purpose, Triggers, Inputs, Outputs, Business Rules, "
                f"Side Effects, Error Paths, Non-Functionals, PII/Compliance.\n\n"
                f"## Module dependency edges\n{edges_text}\n\n"
                f"## Source\n{sources}\n\n{extra_instructions}\n\n"
                f"Output ONLY the markdown body."
            )
            body = await _run_module_agent(msg, repo_root=str(repo_root))
            out = paths.module_brd_path(repo_id, module_id)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body, encoding="utf-8")
            logger.info("[brd] module %s complete", module_id)
            return ModuleBRD(module_id=module_id, body=body)

    module_jobs: list[tuple[str, asyncio.Task[ModuleBRD]]] = []

    for m in inventory.modules:
        edges = [e for e in graph.edges if e.src == m.id or e.dst == m.id]
        module_jobs.append(
            (
                m.id,
                asyncio.create_task(
                    _extract_module(m.id, repo_root / m.path, _render_edges(edges))
                ),
            )
        )

    sys_msg = (
        "Write `_system.md` summarizing cross-module workflows and shared invariants.\n\n"
        f"## All edges\n{_render_edges(graph.edges)}\n\n"
        "Output ONLY the markdown body."
    )
    logger.info("[brd] extracting system view")
    sys_task = asyncio.create_task(_run_system_agent(sys_msg, repo_root=str(repo_root)))

    module_results = await asyncio.gather(*(task for _, task in module_jobs))
    modules_by_id = {module.module_id: module for module in module_results}
    modules = [modules_by_id[m.id] for m in inventory.modules if m.id in modules_by_id]

    sys_body = await sys_task
    sys_path = paths.system_brd_path(repo_id)
    sys_path.parent.mkdir(parents=True, exist_ok=True)
    sys_path.write_text(sys_body, encoding="utf-8")
    logger.info("[brd] system view complete")
    return modules, SystemBRD(body=sys_body)


def _collect_sources(module_dir: Path, max_chars: int = 60_000) -> str:
    chunks: list[str] = []
    used = 0
    for f in sorted(module_dir.rglob("*.py")):
        text = f.read_text(encoding="utf-8", errors="replace")
        block = f"--- {f} ---\n{text}\n"
        if used + len(block) > max_chars:
            chunks.append(f"--- {f} (truncated) ---\n")
            break
        chunks.append(block)
        used += len(block)
    return "\n".join(chunks)


def _render_edges(edges) -> str:
    return "\n".join(f"- {e.src} -[{e.kind}]-> {e.dst}" for e in edges)
