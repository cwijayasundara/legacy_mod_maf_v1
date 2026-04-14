import json
from agent_harness.eval.scorers.base import ScoreResult


def test_score_result_construct_and_serialise():
    r = ScoreResult(stage="graph", score=0.92, passed=True, threshold=0.9,
                    details={"missing_edges": [], "extra_edges": ["x->y:imports"]})
    assert r.stage == "graph"
    assert r.score == 0.92
    assert r.passed is True
    dumped = json.dumps(r.details)
    assert "extra_edges" in dumped


def test_score_result_fail_when_below_threshold():
    r = ScoreResult(stage="inventory", score=0.5, passed=False, threshold=1.0,
                    details={})
    assert r.passed is False
