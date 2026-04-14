from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.pipeline import MigrationPipeline


@pytest.mark.asyncio
async def test_pipeline_forwards_paths_to_analyzer_and_coder(tmp_path, monkeypatch):
    """When source_paths is supplied, analyzer/coder/tester receive the same paths."""
    monkeypatch.chdir(tmp_path)
    pipe = MigrationPipeline(project_root=str(tmp_path))
    await pipe.initialize()

    handler = tmp_path / "handler.py"
    handler.write_text("def handler(e,c): pass\n")

    with patch("agent_harness.pipeline.analyze_module",
               new=AsyncMock(return_value="analysis text")) as azm, \
         patch("agent_harness.pipeline.propose_contract",
               new=AsyncMock(return_value="contract")) as pc, \
         patch("agent_harness.pipeline.finalize_contract",
               new=AsyncMock(return_value="contract")), \
         patch("agent_harness.pipeline.migrate_module",
               new=AsyncMock(return_value="migrated")) as mm, \
         patch("agent_harness.pipeline.evaluate_module",
               new=AsyncMock(return_value="PASS")) as em, \
         patch("agent_harness.pipeline.review_module",
               new=AsyncMock(return_value={"recommendation": "APPROVE",
                                            "confidence_score": 90,
                                            "coverage": 85})) as rm, \
         patch("agent_harness.pipeline.security_review",
               new=AsyncMock(return_value={"recommendation": "APPROVE"})):
        result = await pipe.run(
            module="orders", language="python",
            source_paths=[str(handler)],
            context_paths=[],
        )

    assert result.status in {"completed", "changes_requested"}
    _, kwargs = azm.call_args
    assert kwargs.get("source_paths") == [str(handler)]
    _, kwargs = mm.call_args
    assert kwargs.get("source_paths") == [str(handler)]
    _, kwargs = em.call_args
    assert kwargs.get("source_paths") == [str(handler)]


@pytest.mark.asyncio
async def test_pipeline_defaults_to_legacy_path_when_paths_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src" / "lambda" / "orders").mkdir(parents=True)
    (tmp_path / "src" / "lambda" / "orders" / "handler.py").write_text("pass\n")
    pipe = MigrationPipeline(project_root=str(tmp_path))
    await pipe.initialize()

    with patch("agent_harness.pipeline.analyze_module",
               new=AsyncMock(return_value="analysis")) as azm, \
         patch("agent_harness.pipeline.propose_contract",
               new=AsyncMock(return_value="c")), \
         patch("agent_harness.pipeline.finalize_contract",
               new=AsyncMock(return_value="c")), \
         patch("agent_harness.pipeline.migrate_module",
               new=AsyncMock(return_value="m")), \
         patch("agent_harness.pipeline.evaluate_module",
               new=AsyncMock(return_value="PASS")), \
         patch("agent_harness.pipeline.review_module",
               new=AsyncMock(return_value={"recommendation": "APPROVE",
                                            "confidence_score": 90,
                                            "coverage": 80})), \
         patch("agent_harness.pipeline.security_review",
               new=AsyncMock(return_value={"recommendation": "APPROVE"})):
        await pipe.run(module="orders", language="python")

    _, kwargs = azm.call_args
    assert kwargs.get("source_paths", []) == []
