from pathlib import Path

import pytest

from agent_harness.eval.corpus import load_corpus
from agent_harness.eval.runner import run_corpus, RunArtifacts
from agent_harness.persistence.repository import MigrationRepository


@pytest.mark.asyncio
async def test_run_corpus_deterministic_tier(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = MigrationRepository(db_path=tmp_path / "t.db")
    repo.initialize()
    corpus = load_corpus("synthetic")

    artifacts = await run_corpus(corpus=corpus, tier="deterministic",
                                  repo=repo, repo_id="eval-synth")
    assert isinstance(artifacts, RunArtifacts)
    assert {m.id for m in artifacts.inventory.modules} == {
        "orders", "payments", "notifications"
    }
    edges = {(e.src, e.dst, e.kind) for e in artifacts.graph.edges}
    assert ("orders", "dynamodb_table:Orders", "writes") in edges
    assert set(artifacts.brd.keys()) == {"orders", "payments", "notifications"}
    assert set(artifacts.design.keys()) == {"orders", "payments", "notifications"}
    assert {e.id for e in artifacts.stories.epics} == {"E1", "E2", "E3"}


@pytest.mark.asyncio
async def test_run_corpus_invalid_tier_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = MigrationRepository(db_path=tmp_path / "t.db")
    repo.initialize()
    corpus = load_corpus("synthetic")
    with pytest.raises(ValueError, match="unknown tier"):
        await run_corpus(corpus=corpus, tier="turbo",  # type: ignore
                         repo=repo, repo_id="eval-synth")
