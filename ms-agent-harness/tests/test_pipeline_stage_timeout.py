import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.pipeline import MigrationPipeline
from agent_harness.quality.architecture_checker import check_architecture


def _slow(seconds: float):
    async def _fn(*_, **__):
        await asyncio.sleep(seconds)
        return "analysis"
    return _fn


@pytest.mark.asyncio
async def test_pipeline_analyzer_timeout_marks_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src" / "lambda" / "orders").mkdir(parents=True)
    (tmp_path / "src" / "lambda" / "orders" / "handler.py").write_text("pass\n")
    pipe = MigrationPipeline(project_root=str(tmp_path))
    await pipe.initialize()

    from agent_harness.config import Settings, TimeoutConfig, QualityConfig
    tight = Settings(
        timeouts=TimeoutConfig(per_call_seconds=30,
                                per_stage_seconds={"analyzer": 0.05,
                                                    "coder": 30, "tester": 30,
                                                    "reviewer": 30, "security": 30}),
        quality=QualityConfig(),
    )
    pipe.settings = tight

    with patch("agent_harness.pipeline.analyze_module", new=_slow(1.0)):
        result = await pipe.run(module="orders", language="python")

    assert result.status == "blocked"
    assert "timed out" in (result.message or "").lower()


def test_architecture_checker_skips_virtualenv_like_dirs(tmp_path):
    root = tmp_path
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / ".venv" / "lib" / "service.py").write_text(
        "from api.handlers import x\n"
    )
    (root / "service").mkdir()
    (root / "service" / "worker.py").write_text(
        "from api.handlers import x\n"
    )

    violations = check_architecture(str(root))

    assert violations
    assert all(v.file == "service/worker.py" for v in violations)


@pytest.mark.asyncio
async def test_pipeline_scopes_architecture_check_to_generated_module(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module_dir = tmp_path / "src" / "lambda" / "orders"
    module_dir.mkdir(parents=True)
    (module_dir / "handler.py").write_text("pass\n")

    pipe = MigrationPipeline(project_root=str(tmp_path))
    await pipe.initialize()

    with patch("agent_harness.pipeline.analyze_module", new_callable=AsyncMock, return_value="analysis"), \
         patch("agent_harness.pipeline.propose_contract", new_callable=AsyncMock, return_value='{"checks": []}'), \
         patch("agent_harness.pipeline.finalize_contract", new_callable=AsyncMock, return_value='{"checks": []}'), \
         patch("agent_harness.pipeline.migrate_module", new_callable=AsyncMock, return_value="ok"), \
         patch("agent_harness.pipeline.evaluate_module", new_callable=AsyncMock, return_value="PASS"), \
         patch("agent_harness.pipeline.review_module", new_callable=AsyncMock, return_value={"recommendation": "APPROVE", "confidence": 90}), \
         patch("agent_harness.pipeline.security_review", new_callable=AsyncMock, return_value={"recommendation": "APPROVE"}), \
         patch("agent_harness.pipeline.check_architecture", return_value=[]) as arch_check:
        result = await pipe.run(module="orders", language="python")

    assert result.status == "completed"
    arch_check.assert_called_once_with("migrated_azure_fn/orders")
