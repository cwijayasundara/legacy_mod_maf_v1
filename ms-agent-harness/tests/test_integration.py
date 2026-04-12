"""
Integration tests — verify pipeline orchestration with mocked LLM.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

MOCK_ANALYSIS = "# Analysis\n## Summary\n- Complexity: MEDIUM\n## AWS Dependencies\nDynamoDB, S3"
MOCK_CONTRACT = json.dumps({"module": "order-processor", "contract": {"unit_checks": [{"id": "unit-001"}], "contract_checks": [], "architecture_checks": {}}})
MOCK_MIGRATION_CODE = "import azure.functions as func\n@app.route()\ndef handler(req): pass"
MOCK_TEST_PASS = "Overall Verdict: PASS\nCoverage: 85%"
MOCK_TEST_FAIL = "Overall Verdict: FAIL\nLayer 1: FAIL"
MOCK_REVIEW_APPROVE = {"recommendation": "APPROVE", "confidence_score": 82, "coverage": 85}
MOCK_REVIEW_BLOCK = {"recommendation": "CHANGES_REQUESTED", "confidence_score": 45}


@pytest.fixture
def project_dir(tmp_path):
    lambda_dir = tmp_path / "src" / "lambda" / "order-processor"
    lambda_dir.mkdir(parents=True)
    (lambda_dir / "handler.py").write_text('import boto3\ndef lambda_handler(event, context): pass\n')
    (lambda_dir / "requirements.txt").write_text("boto3>=1.34.0\n")
    (tmp_path / "migration-analysis" / "order-processor").mkdir(parents=True)
    (tmp_path / "src" / "azure-functions" / "order-processor").mkdir(parents=True)
    (tmp_path / "infrastructure" / "order-processor").mkdir(parents=True)
    state_dir = tmp_path / "config" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "learned-rules.md").write_text("# Learned Rules\n")
    (state_dir / "migration-progress.txt").write_text("# Progress\n")
    (state_dir / "coverage-baseline.txt").write_text("80\n")
    (state_dir / "failures.md").write_text("# Failures\n")
    (tmp_path / "config" / "templates").mkdir(parents=True)
    (tmp_path / "config" / "templates" / "sprint-contract.json").write_text("{}")
    (tmp_path / "config" / "templates" / "failure-report.json").write_text("{}")
    (tmp_path / "config" / "program.md").write_text("# Program\n")
    (tmp_path / "config" / "settings.yaml").write_text(
        "models:\n  analyzer: gpt-4o\n  coder: gpt-4o-mini\n"
        "default_profile: balanced\nspeed_profiles:\n  balanced:\n"
        "    description: t\n    token_ceiling: 100000\n    reasoning_effort: medium\n"
        "    max_parallel_chunks: 3\n    complexity_multipliers:\n"
        "      low: 1.5\n      medium: 2.5\n      high: 3.5\n"
        "quality:\n  coverage_floor: 80\n  max_self_healing_attempts: 3\n"
    )
    return tmp_path


@pytest.mark.asyncio
async def test_pipeline_success(project_dir):
    with patch("agent_harness.analyzer.analyze_module", new_callable=AsyncMock, return_value=MOCK_ANALYSIS), \
         patch("agent_harness.coder.propose_contract", new_callable=AsyncMock, return_value=MOCK_CONTRACT), \
         patch("agent_harness.tester.finalize_contract", new_callable=AsyncMock, return_value=MOCK_CONTRACT), \
         patch("agent_harness.coder.migrate_module", new_callable=AsyncMock, return_value=MOCK_MIGRATION_CODE), \
         patch("agent_harness.tester.evaluate_module", new_callable=AsyncMock, return_value=MOCK_TEST_PASS), \
         patch("agent_harness.reviewer.review_module", new_callable=AsyncMock, return_value=MOCK_REVIEW_APPROVE):

        from agent_harness.pipeline import MigrationPipeline
        pipeline = MigrationPipeline(project_root=str(project_dir))
        result = await pipeline.run("order-processor", "python", "WI-TEST")
        assert result.status == "completed"
        assert result.review_score == 82


@pytest.mark.asyncio
async def test_pipeline_self_healing(project_dir):
    call_count = {"n": 0}

    async def mock_tester_evaluate(*a, **kw):
        call_count["n"] += 1
        return MOCK_TEST_FAIL if call_count["n"] < 3 else MOCK_TEST_PASS

    with patch("agent_harness.analyzer.analyze_module", new_callable=AsyncMock, return_value=MOCK_ANALYSIS), \
         patch("agent_harness.coder.propose_contract", new_callable=AsyncMock, return_value=MOCK_CONTRACT), \
         patch("agent_harness.tester.finalize_contract", new_callable=AsyncMock, return_value=MOCK_CONTRACT), \
         patch("agent_harness.coder.migrate_module", new_callable=AsyncMock, return_value=MOCK_MIGRATION_CODE), \
         patch("agent_harness.tester.evaluate_module", side_effect=mock_tester_evaluate), \
         patch("agent_harness.reviewer.review_module", new_callable=AsyncMock, return_value=MOCK_REVIEW_APPROVE):

        from agent_harness.pipeline import MigrationPipeline
        pipeline = MigrationPipeline(project_root=str(project_dir))
        result = await pipeline.run("order-processor", "python")
        assert result.status == "completed"
        assert call_count["n"] == 3


@pytest.mark.asyncio
async def test_pipeline_blocked(project_dir):
    with patch("agent_harness.analyzer.analyze_module", new_callable=AsyncMock, return_value=MOCK_ANALYSIS), \
         patch("agent_harness.coder.propose_contract", new_callable=AsyncMock, return_value=MOCK_CONTRACT), \
         patch("agent_harness.tester.finalize_contract", new_callable=AsyncMock, return_value=MOCK_CONTRACT), \
         patch("agent_harness.coder.migrate_module", new_callable=AsyncMock, return_value=MOCK_MIGRATION_CODE), \
         patch("agent_harness.tester.evaluate_module", new_callable=AsyncMock, return_value=MOCK_TEST_FAIL):

        from agent_harness.pipeline import MigrationPipeline
        pipeline = MigrationPipeline(project_root=str(project_dir))
        result = await pipeline.run("order-processor", "python")
        assert result.status == "blocked"
        assert (project_dir / "migration-analysis" / "order-processor" / "blocked.md").exists()


@pytest.mark.asyncio
async def test_pipeline_changes_requested(project_dir):
    with patch("agent_harness.analyzer.analyze_module", new_callable=AsyncMock, return_value=MOCK_ANALYSIS), \
         patch("agent_harness.coder.propose_contract", new_callable=AsyncMock, return_value=MOCK_CONTRACT), \
         patch("agent_harness.tester.finalize_contract", new_callable=AsyncMock, return_value=MOCK_CONTRACT), \
         patch("agent_harness.coder.migrate_module", new_callable=AsyncMock, return_value=MOCK_MIGRATION_CODE), \
         patch("agent_harness.tester.evaluate_module", new_callable=AsyncMock, return_value=MOCK_TEST_PASS), \
         patch("agent_harness.reviewer.review_module", new_callable=AsyncMock, return_value=MOCK_REVIEW_BLOCK):

        from agent_harness.pipeline import MigrationPipeline
        pipeline = MigrationPipeline(project_root=str(project_dir))
        result = await pipeline.run("order-processor", "python")
        assert result.status == "changes_requested"
