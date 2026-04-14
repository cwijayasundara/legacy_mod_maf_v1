import json

from agent_harness.eval.report import render, ReportBundle
from agent_harness.eval.scorers.base import ScoreResult


def _results():
    return [
        ScoreResult(stage="inventory", score=1.0, passed=True, threshold=1.0,
                    details={"missing": [], "extra": []}),
        ScoreResult(stage="graph", score=0.95, passed=True, threshold=0.9,
                    details={"missing_edges": []}),
        ScoreResult(stage="stories", score=0.9, passed=True, threshold=0.85,
                    details={}),
        ScoreResult(stage="brd", score=0.8, passed=True, threshold=0.7,
                    details={}),
        ScoreResult(stage="design", score=0.65, passed=False, threshold=0.7,
                    details={"missing_module_designs": ["x"]}),
    ]


def test_render_writes_json_and_markdown(tmp_path):
    bundle = render(_results(), corpus_name="synthetic", tier="real_llm",
                     out_dir=tmp_path)
    assert isinstance(bundle, ReportBundle)
    assert bundle.overall_passed is False
    assert (bundle.run_dir / "report.json").exists()
    assert (bundle.run_dir / "report.md").exists()

    data = json.loads((bundle.run_dir / "report.json").read_text())
    assert data["overall_passed"] is False
    assert {r["stage"] for r in data["results"]} == {
        "inventory", "graph", "stories", "brd", "design"
    }
    md = (bundle.run_dir / "report.md").read_text()
    assert "FAIL" in md
    assert "design" in md


def test_render_passes_when_all_pass(tmp_path):
    all_pass = [ScoreResult(stage="inventory", score=1.0, passed=True,
                            threshold=1.0, details={})]
    bundle = render(all_pass, corpus_name="synthetic", tier="deterministic",
                     out_dir=tmp_path)
    assert bundle.overall_passed is True
    md = (bundle.run_dir / "report.md").read_text()
    assert "PASS" in md


def test_render_run_dir_is_timestamped(tmp_path):
    bundle = render(_results(), corpus_name="synthetic", tier="real_llm",
                     out_dir=tmp_path)
    assert bundle.run_dir.name.endswith("-synthetic")
    assert bundle.run_dir.parent == tmp_path
