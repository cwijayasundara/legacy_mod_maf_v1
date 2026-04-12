"""Shared pytest fixtures for codex-harness tests."""

import os
import shutil
import tempfile

import pytest

# Sample handler.py content (mirrors sample/lambda/handler.py)
_SAMPLE_HANDLER = """\
import json

def lambda_handler(event, context):
    return {"statusCode": 200, "body": json.dumps({"ok": True})}
"""

_COVERAGE_BASELINE = """\
# Coverage Ratchet Baseline
# This value only goes UP, never down.
# Format: single integer representing minimum coverage percentage.
# Updated after each successful migration that achieves higher coverage.
80
"""

_LEARNED_RULES = """\
# Learned Rules
- Always pin dependency versions
"""

_MIGRATION_PROGRESS = ""  # empty by default; individual tests populate as needed


@pytest.fixture()
def tmp_project(tmp_path):
    """
    Create a temporary directory tree that mirrors the expected codex-harness
    project layout:

        <root>/
            src/lambda/order-processor/handler.py
            migration-analysis/
            state/
                coverage-baseline.txt
                learned-rules.md
                migration-progress.txt
                failures.md
    """
    root = tmp_path / "project"
    root.mkdir()

    # Source module
    src_dir = root / "src" / "lambda" / "order-processor"
    src_dir.mkdir(parents=True)
    (src_dir / "handler.py").write_text(_SAMPLE_HANDLER)

    # Migration analysis output dir
    (root / "migration-analysis").mkdir()

    # State directory with baseline files
    state_dir = root / "state"
    state_dir.mkdir()
    (state_dir / "coverage-baseline.txt").write_text(_COVERAGE_BASELINE)
    (state_dir / "learned-rules.md").write_text(_LEARNED_RULES)
    (state_dir / "migration-progress.txt").write_text(_MIGRATION_PROGRESS)
    (state_dir / "failures.md").write_text("")

    return root
