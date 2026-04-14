from agent_harness.discovery.artifacts import (
    AcceptanceCriterion, Epic, Stories, Story,
)
from agent_harness.eval.scorers.stories import score


def _story(sid, epic, deps=()):
    return Story(id=sid, epic_id=epic, title="t", description="d",
                 acceptance_criteria=[AcceptanceCriterion(text="ac")],
                 depends_on=list(deps), blocks=[], estimate="M")


def _stories(epic_to_module, stories):
    epics = [Epic(id=eid, module_id=mod, title="E",
                  story_ids=[s.id for s in stories if s.epic_id == eid])
             for eid, mod in epic_to_module.items()]
    return Stories(epics=epics, stories=stories)


def test_perfect_shape_scores_one():
    s = _stories(
        {"E1": "orders", "E2": "payments", "E3": "notifications"},
        [_story("S1", "E1"), _story("S2", "E2", ["S1"]),
         _story("S3", "E3", ["S2"])],
    )
    expected = {
        "expected_epic_modules": ["orders", "payments", "notifications"],
        "expected_story_count_per_module": {"orders": 1, "payments": 1,
                                             "notifications": 1},
        "expected_dep_edges": [["payments", "orders"], ["notifications", "payments"]],
    }
    r = score(s, expected)
    assert r.stage == "stories"
    assert r.score == 1.0
    assert r.passed is True


def test_missing_epic_for_module_drops_score():
    s = _stories({"E1": "orders"}, [_story("S1", "E1")])
    expected = {
        "expected_epic_modules": ["orders", "payments"],
        "expected_story_count_per_module": {"orders": 1, "payments": 1},
        "expected_dep_edges": [],
    }
    r = score(s, expected)
    assert r.score < r.threshold
    assert r.passed is False


def test_story_without_ac_fails_ac_check():
    bad_story = Story(id="S1", epic_id="E1", title="t", description="d",
                      acceptance_criteria=[], depends_on=[], blocks=[], estimate="M")
    s = _stories({"E1": "orders"}, [bad_story])
    expected = {
        "expected_epic_modules": ["orders"],
        "expected_story_count_per_module": {"orders": 1},
        "expected_dep_edges": [],
    }
    r = score(s, expected)
    assert r.score < 1.0
    assert r.details["ac_coverage"] == 0.0


def test_dep_edge_shape_compared_on_modules_not_story_ids():
    s = _stories(
        {"E1": "orders", "E2": "payments"},
        [_story("SX", "E1"), _story("SY", "E2", ["SX"])],
    )
    expected = {
        "expected_epic_modules": ["orders", "payments"],
        "expected_story_count_per_module": {"orders": 1, "payments": 1},
        "expected_dep_edges": [["payments", "orders"]],
    }
    r = score(s, expected)
    assert r.details["dep_edge_jaccard"] == 1.0


def test_threshold_is_0_85():
    s = _stories({"E1": "orders"}, [_story("S1", "E1")])
    expected = {"expected_epic_modules": ["orders"],
                "expected_story_count_per_module": {"orders": 1},
                "expected_dep_edges": []}
    r = score(s, expected)
    assert r.threshold == 0.85
