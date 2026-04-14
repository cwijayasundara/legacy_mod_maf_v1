from agent_harness.discovery.artifacts import Inventory, ModuleRecord
from agent_harness.eval.scorers.inventory import score


def _inv(ids: list[str]) -> Inventory:
    return Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id=i, path=i, language="python",
                         handler_entrypoint=f"{i}/handler.py",
                         loc=1, config_files=[])
            for i in ids
        ],
    )


def test_exact_match_scores_one_and_passes():
    got = _inv(["orders", "payments", "notifications"])
    expected = _inv(["orders", "payments", "notifications"])
    r = score(got, expected)
    assert r.stage == "inventory"
    assert r.score == 1.0
    assert r.passed is True
    assert r.details == {"missing": [], "extra": []}


def test_missing_module_fails():
    got = _inv(["orders"])
    expected = _inv(["orders", "payments"])
    r = score(got, expected)
    assert r.score == 0.5
    assert r.passed is False
    assert r.details["missing"] == ["payments"]
    assert r.details["extra"] == []


def test_extra_module_still_fails_threshold():
    got = _inv(["orders", "bogus"])
    expected = _inv(["orders"])
    r = score(got, expected)
    assert r.passed is False
    assert r.details["extra"] == ["bogus"]


def test_threshold_is_one():
    got = _inv(["orders", "payments"])
    expected = _inv(["orders", "payments"])
    r = score(got, expected)
    assert r.threshold == 1.0
