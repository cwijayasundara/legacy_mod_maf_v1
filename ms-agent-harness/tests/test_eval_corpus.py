from pathlib import Path

from agent_harness.eval.corpus import Corpus, load_corpus


def test_load_synthetic_corpus():
    c = load_corpus("synthetic")
    assert c.name == "synthetic"
    assert c.repo_path.is_dir()
    assert {m.id for m in c.expected_inventory.modules} == {
        "orders", "payments", "notifications"
    }
    edges = {(e.src, e.dst, e.kind) for e in c.expected_graph.edges}
    assert ("orders", "dynamodb_table:Orders", "writes") in edges
    assert sorted(c.expected_stories["expected_epic_modules"]) == [
        "notifications", "orders", "payments"
    ]


def test_load_unknown_corpus_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_corpus("does-not-exist")
