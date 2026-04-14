"""RepoScanner — LLM agent that produces an Inventory."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import CriticReport, Inventory
from . import paths

logger = logging.getLogger("discovery.scanner")

_TREE_LIMIT = 200


def _list_tree(root: Path) -> list[str]:
    out = []
    for p in sorted(root.rglob("*")):
        if any(seg in {".git", "__pycache__", "node_modules", ".venv"}
               for seg in p.parts):
            continue
        out.append(str(p.relative_to(root)))
        if len(out) >= _TREE_LIMIT:
            break
    return out


async def _run_agent(message: str, repo_root: str | None = None) -> str:
    """Indirection point so tests can patch a single seam."""
    agent = create_agent(role="repo_scanner",
                         tools=[read_file, list_directory, search_files],
                         repo_root=repo_root)
    return await run_with_retry(agent, message)


async def scan_repo(repo_id: str, repo_path: str,
                    extra_instructions: str = "") -> Inventory:
    root = Path(repo_path).resolve()
    listing = "\n".join(_list_tree(root))
    now = datetime.now(timezone.utc).isoformat()
    msg = (
        f"repo_path: {root}\n"
        f"discovered_at: {now}\n\n"
        f"## File tree (truncated to {_TREE_LIMIT} entries)\n{listing}\n\n"
        f"{extra_instructions}\n\n"
        f"Return ONLY the JSON object."
    )
    raw = await _run_agent(msg, repo_root=str(root))
    inv = Inventory.model_validate_json(_strip_fences(raw))

    out_path = paths.inventory_path(repo_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(inv.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Wrote inventory to %s (%d modules)", out_path, len(inv.modules))
    return inv


def sanity_check(inv: Inventory, repo_root: Path) -> CriticReport:
    """Deterministic post-check — no LLM. Used in lieu of a critic for scanner."""
    reasons: list[str] = []
    for m in inv.modules:
        handler = (repo_root / m.handler_entrypoint)
        if not handler.is_file():
            reasons.append(f"handler not found: {m.handler_entrypoint}")
            continue
        ext = handler.suffix.lower()
        ext_to_lang = {".py": "python", ".js": "node", ".ts": "node",
                       ".java": "java", ".cs": "csharp"}
        expected = ext_to_lang.get(ext)
        if expected and m.language != expected:
            reasons.append(
                f"module {m.id}: language={m.language} but extension implies {expected}"
            )
    return CriticReport(
        verdict="PASS" if not reasons else "FAIL",
        reasons=reasons,
        suggestions=[],
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
