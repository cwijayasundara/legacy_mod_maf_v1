"""BRDExtractor — produces per-module + system BRD markdown."""
from __future__ import annotations

import logging
from pathlib import Path

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import DependencyGraph, Inventory, ModuleBRD, SystemBRD
from . import paths

logger = logging.getLogger("discovery.brd")


async def _run_module_agent(message: str) -> str:
    agent = create_agent(role="brd_extractor",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def _run_system_agent(message: str) -> str:
    agent = create_agent(role="brd_extractor",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def extract_brds(repo_id: str, repo_root: Path,
                       inventory: Inventory, graph: DependencyGraph,
                       extra_instructions: str = "") -> tuple[list[ModuleBRD], SystemBRD]:
    repo_root = Path(repo_root).resolve()
    modules: list[ModuleBRD] = []

    for m in inventory.modules:
        sources = _collect_sources(repo_root / m.path)
        edges = [e for e in graph.edges if e.src == m.id or e.dst == m.id]
        msg = (
            f"Write a BRD markdown for module `{m.id}`.\n\n"
            f"Required sections: Purpose, Triggers, Inputs, Outputs, Business Rules, "
            f"Side Effects, Error Paths, Non-Functionals, PII/Compliance.\n\n"
            f"## Module dependency edges\n{_render_edges(edges)}\n\n"
            f"## Source\n{sources}\n\n{extra_instructions}\n\n"
            f"Output ONLY the markdown body."
        )
        body = await _run_module_agent(msg)
        brd = ModuleBRD(module_id=m.id, body=body)
        out = paths.module_brd_path(repo_id, m.id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
        modules.append(brd)

    sys_msg = (
        "Write `_system.md` summarizing cross-module workflows and shared invariants.\n\n"
        f"## All edges\n{_render_edges(graph.edges)}\n\n"
        "Output ONLY the markdown body."
    )
    sys_body = await _run_system_agent(sys_msg)
    paths.system_brd_path(repo_id).write_text(sys_body, encoding="utf-8")
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
