"""Shared path helpers — every migration artifact routes through here.

`MIGRATED_DIR` is the single root for generated output. Layout underneath it:

    <MIGRATED_DIR>/
      <module>/                — migrated Azure Functions (code + tests)
      analysis/<module>/       — analyzer output, reviews, security review
      discovery/<repo_id>/     — inventory, graph, BRDs, designs, backlog
      infrastructure/<module>/ — Bicep templates

All helpers return absolute paths when `MIGRATED_DIR` is absolute; otherwise
they resolve against the current working directory.
"""

from __future__ import annotations

import os
from pathlib import Path


def migrated_root() -> Path:
    return Path(os.getenv("MIGRATED_DIR", "src/azure-functions"))


def migrated_dir(module: str) -> Path:
    return migrated_root() / module


def analysis_root() -> Path:
    return migrated_root() / "analysis"


def analysis_dir(module: str) -> Path:
    return analysis_root() / module


def infra_root() -> Path:
    return migrated_root() / "infrastructure"


def infra_dir(module: str) -> Path:
    return infra_root() / module


def discovery_root() -> Path:
    return migrated_root() / "discovery"


def discovery_dir(repo_id: str) -> Path:
    return discovery_root() / repo_id
