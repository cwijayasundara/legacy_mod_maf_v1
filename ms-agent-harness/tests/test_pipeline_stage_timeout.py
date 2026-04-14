import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.pipeline import MigrationPipeline


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
