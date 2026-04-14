import pytest
from agent_harness.discovery.artifacts import (
    Stories, Story, Epic, AcceptanceCriterion, Backlog, BacklogItem,
)
from agent_harness.discovery.wave_scheduler import schedule, CycleError


def _story(sid, deps=(), epic="E1", title="t"):
    return Story(
        id=sid, epic_id=epic, title=title, description="d",
        acceptance_criteria=[AcceptanceCriterion(text="ac")],
        depends_on=list(deps), blocks=[], estimate="M",
    )


def _stories(stories, modules=("orders",)):
    epics = [Epic(id="E1", module_id=modules[0], title="E", story_ids=[s.id for s in stories])]
    return Stories(epics=epics, stories=list(stories))


def test_linear_chain_produces_consecutive_waves():
    s = _stories([_story("A"), _story("B", ["A"]), _story("C", ["B"])])
    backlog = schedule(s, language_by_module={"orders": "python"})
    assert {item.wave for item in backlog.items} == {1, 2, 3}


def test_independent_stories_share_first_wave():
    s = _stories([_story("A"), _story("B"), _story("C", ["A"])])
    backlog = schedule(s, language_by_module={"orders": "python"})
    assert sorted(item.wave for item in backlog.items) == [1, 1, 2]


def test_cycle_raises():
    s = _stories([_story("A", ["B"]), _story("B", ["A"])])
    with pytest.raises(CycleError) as exc:
        schedule(s, language_by_module={"orders": "python"})
    assert "A" in str(exc.value) and "B" in str(exc.value)


def test_unknown_dependency_raises():
    s = _stories([_story("A", ["GHOST"])])
    with pytest.raises(ValueError, match="GHOST"):
        schedule(s, language_by_module={"orders": "python"})


def test_backlog_items_are_ordered_by_wave():
    s = _stories([_story("C", ["A", "B"]), _story("A"), _story("B")])
    backlog = schedule(s, language_by_module={"orders": "python"})
    waves = [item.wave for item in backlog.items]
    assert waves == sorted(waves)


def test_backlog_item_carries_acceptance_criteria_text():
    s = _stories([_story("A")])
    s.stories[0].acceptance_criteria.append(AcceptanceCriterion(text="ac2"))
    backlog = schedule(s, language_by_module={"orders": "python"})
    assert "ac" in backlog.items[0].acceptance_criteria
    assert "ac2" in backlog.items[0].acceptance_criteria
