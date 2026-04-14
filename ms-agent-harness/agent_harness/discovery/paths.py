"""Single source of truth for discovery artifact paths."""
from pathlib import Path

DISCOVERY_ROOT = Path("discovery")


def repo_dir(repo_id: str) -> Path:
    return DISCOVERY_ROOT / repo_id


def inventory_path(repo_id: str) -> Path:
    return repo_dir(repo_id) / "inventory.json"


def graph_path(repo_id: str) -> Path:
    return repo_dir(repo_id) / "graph.json"


def brd_dir(repo_id: str) -> Path:
    return repo_dir(repo_id) / "brd"


def module_brd_path(repo_id: str, module_id: str) -> Path:
    return brd_dir(repo_id) / f"{module_id}.md"


def system_brd_path(repo_id: str) -> Path:
    return brd_dir(repo_id) / "_system.md"


def design_dir(repo_id: str) -> Path:
    return repo_dir(repo_id) / "design"


def module_design_path(repo_id: str, module_id: str) -> Path:
    return design_dir(repo_id) / f"{module_id}.md"


def system_design_path(repo_id: str) -> Path:
    return design_dir(repo_id) / "_system.md"


def stories_path(repo_id: str) -> Path:
    return repo_dir(repo_id) / "stories.json"


def backlog_path(repo_id: str) -> Path:
    return repo_dir(repo_id) / "backlog.json"


def blocked_path(repo_id: str, stage: str) -> Path:
    return repo_dir(repo_id) / stage / "blocked.md"
