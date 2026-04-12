"""Tests for orchestrator/state_manager.py — pure logic, no cloud calls."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness", "orchestrator"))

from state_manager import StateManager, STATE_FILES, ModuleProgress


def _make_sm(tmp_project):
    """Create a StateManager in local-only mode (no connection string)."""
    return StateManager(
        connection_string="",
        container_name="test",
        local_state_dir=str(tmp_project / "state"),
    )


# ---------- tests ----------


@pytest.mark.asyncio
async def test_local_state_read_write(tmp_project):
    """Write a state file, verify it can be read back."""
    sm = _make_sm(tmp_project)
    await sm.initialize()

    state_dir = tmp_project / "state"
    (state_dir / "learned-rules.md").write_text("# rule-1\n- foo\n")

    content = (state_dir / "learned-rules.md").read_text()
    assert "rule-1" in content


@pytest.mark.asyncio
async def test_coverage_baseline(tmp_project):
    """Read the default coverage-baseline.txt and verify the value is 80."""
    sm = _make_sm(tmp_project)
    await sm.initialize()

    baseline_path = tmp_project / "state" / "coverage-baseline.txt"
    text = baseline_path.read_text()
    # The last non-empty line should be the numeric baseline
    value = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    assert len(value) == 1
    assert int(value[0]) == 80


@pytest.mark.asyncio
async def test_pull_push_local_only(tmp_project):
    """pull/push should succeed silently when blob storage is not configured."""
    sm = _make_sm(tmp_project)
    await sm.initialize()

    assert not sm.is_connected()
    # These should be no-ops without raising
    await sm.pull_state()
    await sm.push_state()


@pytest.mark.asyncio
async def test_get_module_progress(tmp_project):
    """Write a migration-progress.txt with a session block and parse it back."""
    sm = _make_sm(tmp_project)
    await sm.initialize()

    progress_text = """\
=== Session 2026-01-15 ===
module: order-processor
recommendation: APPROVE
coverage: 92%
reviewer_score: 7/8
gates_passed: [1, 2, 3, 4, 5, 6, 7]
gates_failed: [8]
blocked: false
"""
    (tmp_project / "state" / "migration-progress.txt").write_text(progress_text)

    progress = await sm.get_module_progress("order-processor")
    assert progress is not None
    assert progress.module == "order-processor"
    assert progress.status == "approve"
    assert progress.coverage == 92.0
    assert progress.reviewer_score == 7
    assert 1 in progress.gates_passed
    assert 8 in progress.gates_failed
    assert progress.blocked is False


@pytest.mark.asyncio
async def test_get_all_progress(tmp_project):
    """Write session blocks for two modules and verify both are returned."""
    sm = _make_sm(tmp_project)
    await sm.initialize()

    progress_text = """\
=== Session 2026-01-10 ===
module: auth-handler
recommendation: APPROVE
coverage: 85%

=== Session 2026-01-15 ===
module: order-processor
recommendation: CHANGES_REQUESTED
coverage: 70%
"""
    (tmp_project / "state" / "migration-progress.txt").write_text(progress_text)

    results = await sm.get_all_progress()
    assert len(results) == 2
    modules = {r.module for r in results}
    assert modules == {"auth-handler", "order-processor"}
