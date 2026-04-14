"""Integration: pipeline derives repo_root + module_path and threads them."""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.pipeline import MigrationPipeline


@pytest.mark.asyncio
async def test_pipeline_derives_and_threads_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    repo = tmp_path / "repo"; repo.mkdir()
    module = repo / "mod"; module.mkdir()
    handler = module / "handler.py"; handler.write_text("def handler(e,c): pass\n")

    pipe = MigrationPipeline(project_root=str(tmp_path))
    await pipe.initialize()

    with patch("agent_harness.pipeline.analyze_module",
               new=AsyncMock(return_value="analysis")) as azm, \
         patch("agent_harness.pipeline.propose_contract",
               new=AsyncMock(return_value="c")), \
         patch("agent_harness.pipeline.finalize_contract",
               new=AsyncMock(return_value="c")), \
         patch("agent_harness.pipeline.migrate_module",
               new=AsyncMock(return_value="m")) as mm, \
         patch("agent_harness.pipeline.evaluate_module",
               new=AsyncMock(return_value="PASS")) as em, \
         patch("agent_harness.pipeline.review_module",
               new=AsyncMock(return_value={"recommendation": "APPROVE",
                                            "confidence_score": 90,
                                            "coverage": 80})) as rm, \
         patch("agent_harness.pipeline.security_review",
               new=AsyncMock(return_value={"recommendation": "APPROVE"})) as sm:
        await pipe.run(
            module="mod", language="python",
            source_paths=[str(handler)],
        )

    # Every stage should have received repo_root = the repo dir
    # and module_path = the module dir.
    expected_module_path = str(module.resolve())
    for call in (azm, mm, em, rm, sm):
        kwargs = call.call_args.kwargs
        assert kwargs.get("module_path") == expected_module_path, (
            f"{call} got module_path={kwargs.get('module_path')!r}")
        # repo_root can be the repo dir OR any ancestor containing the module;
        # with a single source_path under /tmp/.../repo/mod/handler.py and no
        # context_paths, the common-ancestor falls on the module's parent dir.
        assert kwargs.get("repo_root") in (str(repo.resolve()),
                                            expected_module_path)


@pytest.mark.asyncio
async def test_pipeline_legacy_path_uses_project_root(tmp_path, monkeypatch):
    """With no source_paths, falls back to PROJECT_ROOT + src/lambda/<module>/."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src" / "lambda" / "orders").mkdir(parents=True)
    (tmp_path / "src" / "lambda" / "orders" / "handler.py").write_text("pass\n")

    pipe = MigrationPipeline(project_root=str(tmp_path))
    await pipe.initialize()

    with patch("agent_harness.pipeline.analyze_module",
               new=AsyncMock(return_value="a")) as azm, \
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

    kwargs = azm.call_args.kwargs
    assert kwargs.get("repo_root") == str(tmp_path)
    assert kwargs.get("module_path") == str(tmp_path / "src" / "lambda" / "orders")
