"""Discovery & Planning subpackage.

Public entry points:
- run_discovery(repo_id, repo_path, repo) — runs the 5 LLM stages.
- run_planning(repo_id, repo) — runs WaveScheduler over stored artifacts.

See docs/superpowers/specs/2026-04-14-discovery-planning-layer-design.md.
"""
from .workflow import run_discovery, run_planning

__all__ = ["run_discovery", "run_planning"]
