"""Tests for pipeline.py — mocked Copilot CLI calls."""

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def project_dir(tmp_path):
    """Create minimal project structure for pipeline tests."""
    (tmp_path / "src" / "lambda" / "order-processor").mkdir(parents=True)
    (tmp_path / "src" / "lambda" / "order-processor" / "handler.py").write_text("def handler(): pass")
    (tmp_path / "migration-analysis" / "order-processor").mkdir(parents=True)
    (tmp_path / "src" / "azure-functions" / "order-processor").mkdir(parents=True)
    (tmp_path / "infrastructure" / "order-processor").mkdir(parents=True)
    state = tmp_path / "config" / "state"
    state.mkdir(parents=True)
    (state / "learned-rules.md").write_text("# Rules\n")
    (state / "migration-progress.txt").write_text("# Progress\n")
    (state / "coverage-baseline.txt").write_text("80\n")
    (tmp_path / "config" / "settings.yaml").write_text("copilot:\n  max_autopilot_continues: 5\n")
    return tmp_path


@pytest.mark.asyncio
async def test_pipeline_completed(project_dir):
    """Copilot succeeds, review approves → completed."""
    # Create expected output artifacts
    ma = project_dir / "migration-analysis" / "order-processor"
    (ma / "analysis.md").write_text("# Analysis\nComplexity: MEDIUM")
    (ma / "sprint-contract.json").write_text("{}")
    (ma / "test-results.md").write_text("All tests PASS")
    (ma / "review.md").write_text("## Confidence Score: 85/100\n## Recommendation: APPROVE")

    with patch("harness.copilot_runner.CopilotRunner.run", new_callable=AsyncMock, return_value=(True, "done")), \
         patch("harness.sdk_agents.security_review_via_sdk", new_callable=AsyncMock, return_value={"recommendation": "APPROVE", "automated_findings": 0, "blockers": 0}):

        from harness.pipeline import MigrationPipeline
        pipeline = MigrationPipeline(project_root=str(project_dir))
        result = await pipeline.run("order-processor", "python")

        assert result.status == "completed"
        assert result.review_score == 85


@pytest.mark.asyncio
async def test_pipeline_blocked(project_dir):
    """Copilot produces blocked.md → blocked."""
    (project_dir / "migration-analysis" / "order-processor" / "blocked.md").write_text("Blocked")

    with patch("harness.copilot_runner.CopilotRunner.run", new_callable=AsyncMock, return_value=(True, "done")):

        from harness.pipeline import MigrationPipeline
        pipeline = MigrationPipeline(project_root=str(project_dir))
        result = await pipeline.run("order-processor", "python")

        assert result.status == "blocked"


@pytest.mark.asyncio
async def test_pipeline_security_blocked(project_dir):
    """Migration passes but security blocks → security_blocked."""
    ma = project_dir / "migration-analysis" / "order-processor"
    (ma / "analysis.md").write_text("# Analysis")
    (ma / "sprint-contract.json").write_text("{}")
    (ma / "test-results.md").write_text("PASS")
    (ma / "review.md").write_text("## Confidence Score: 80/100\n## Recommendation: APPROVE")

    with patch("harness.copilot_runner.CopilotRunner.run", new_callable=AsyncMock, return_value=(True, "done")), \
         patch("harness.sdk_agents.security_review_via_sdk", new_callable=AsyncMock, return_value={"recommendation": "BLOCKED", "automated_findings": 2, "blockers": 1}):

        from harness.pipeline import MigrationPipeline
        pipeline = MigrationPipeline(project_root=str(project_dir))
        result = await pipeline.run("order-processor", "python")

        assert result.status == "security_blocked"
        assert 7 in result.gates_failed
