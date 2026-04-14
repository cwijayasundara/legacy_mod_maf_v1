"""Stories-stage scorer — epic/count/dep-edge shape + AC coverage."""
from __future__ import annotations

from typing import Any

from ...discovery.artifacts import Stories
from .base import ScoreResult

THRESHOLD = 0.85


def score(got: Stories, expected: dict[str, Any]) -> ScoreResult:
    epic_module = {e.id: e.module_id for e in got.epics}
    story_module = {s.id: epic_module.get(s.epic_id, s.epic_id) for s in got.stories}

    expected_modules = set(expected.get("expected_epic_modules", []))
    got_modules_with_epics = {e.module_id for e in got.epics}
    if not expected_modules:
        epic_coverage = 1.0
    else:
        epic_coverage = len(got_modules_with_epics & expected_modules) / len(expected_modules)

    counts_by_mod: dict[str, int] = {}
    for s in got.stories:
        m = story_module.get(s.id)
        if m is not None:
            counts_by_mod[m] = counts_by_mod.get(m, 0) + 1
    expected_counts = expected.get("expected_story_count_per_module", {})
    if not expected_counts:
        count_score = 1.0
    else:
        hits = sum(
            1 for mod, want in expected_counts.items()
            if counts_by_mod.get(mod, 0) > 0
            and abs(counts_by_mod.get(mod, 0) - want) <= 1
        )
        count_score = hits / len(expected_counts)

    got_module_edges: set[tuple[str, str]] = set()
    for s in got.stories:
        src_mod = story_module.get(s.id)
        for dep in s.depends_on:
            dst_mod = story_module.get(dep)
            if src_mod and dst_mod and src_mod != dst_mod:
                got_module_edges.add((src_mod, dst_mod))
    expected_edges = {(a, b) for a, b in expected.get("expected_dep_edges", [])}
    union = got_module_edges | expected_edges
    dep_edge_jaccard = 1.0 if not union else len(got_module_edges & expected_edges) / len(union)

    if not got.stories:
        ac_coverage = 1.0 if not expected_modules else 0.0
    else:
        ac_coverage = sum(1 for s in got.stories if s.acceptance_criteria) / len(got.stories)

    total = (epic_coverage + count_score + dep_edge_jaccard + ac_coverage) / 4
    passed = total >= THRESHOLD

    return ScoreResult(
        stage="stories", score=total, passed=passed, threshold=THRESHOLD,
        details={
            "epic_coverage": epic_coverage,
            "count_score": count_score,
            "dep_edge_jaccard": dep_edge_jaccard,
            "ac_coverage": ac_coverage,
            "got_module_edges": sorted(list(e) for e in got_module_edges),
            "expected_module_edges": sorted(list(e) for e in expected_edges),
        },
    )
