# Evaluation Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a regression-focused evaluation framework that scores the five discovery-pipeline stages against two golden corpora (`synthetic`, `aws_legacy`), runs in two tiers (deterministic / real-LLM), and gates on per-stage thresholds with a 0/1 exit code.

**Architecture:** New `agent_harness/eval/` subpackage. Five scorers (inventory, graph, stories — structured; brd, design — structural + LLM-as-judge). Shared `Judge` helper reads YAML rubrics. `Runner` patches `_run_agent` seams for the deterministic tier or calls the real pipeline for the real-LLM tier. `Report` aggregates `ScoreResult`s into JSON + markdown. CLI via `python -m agent_harness.eval`.

**Tech Stack:** Python 3.11, Pydantic v2, PyYAML, `pytest` + `pytest-asyncio`. All paths in this plan are relative to `ms-agent-harness/` unless stated otherwise. Pre-existing failures in `tests/test_chunker.py`, `test_complexity_scorer.py`, `test_compressor.py`, `test_token_estimator.py`, `test_integration.py`, `test_ast_tools.py` are unrelated — scope regression checks only to files this plan touches. Run tests with `python3 -m pytest`.

---

## File Structure

| File | Responsibility |
|---|---|
| `agent_harness/eval/__init__.py` | Public re-exports of top-level API |
| `agent_harness/eval/__main__.py` | CLI entry (`run`, `report` subcommands) |
| `agent_harness/eval/corpus.py` | `Corpus` dataclass + `load_corpus` from `tests/eval_corpus/` |
| `agent_harness/eval/runner.py` | `run_corpus(corpus, tier, repo)` → `RunArtifacts` |
| `agent_harness/eval/judge.py` | `Judge.score(rubric, artifact, context)` LLM-as-judge helper + `Rubric` loader |
| `agent_harness/eval/report.py` | `render(results, corpus, tier, out_dir)` → JSON + markdown on disk |
| `agent_harness/eval/scorers/__init__.py` | Re-exports |
| `agent_harness/eval/scorers/base.py` | `ScoreResult` dataclass |
| `agent_harness/eval/scorers/inventory.py` | Scanner-stage scorer (exact-match on module IDs) |
| `agent_harness/eval/scorers/graph.py` | Grapher-stage scorer (edge + resource-node Jaccard) |
| `agent_harness/eval/scorers/stories.py` | Stories-stage scorer (epic/count/dep-edge shape) |
| `agent_harness/eval/scorers/brd.py` | Structural + judge scorer |
| `agent_harness/eval/scorers/design.py` | Structural + judge scorer |
| `agent_harness/eval/rubrics/brd.yaml` | Rubric for BRD judge |
| `agent_harness/eval/rubrics/design.yaml` | Rubric for architect judge |
| `tests/eval_corpus/synthetic/corpus.yaml` | Corpus metadata |
| `tests/eval_corpus/synthetic/expected_inventory.json` | Hand-authored ground truth |
| `tests/eval_corpus/synthetic/expected_graph.json` | Hand-authored ground truth |
| `tests/eval_corpus/synthetic/expected_stories_shape.json` | Hand-authored ground truth |
| `tests/eval_corpus/synthetic/canned/*.json` | Canned LLM responses for deterministic tier |
| `tests/test_eval_base.py` | `ScoreResult` sanity |
| `tests/test_eval_inventory_scorer.py` | Inventory scorer |
| `tests/test_eval_graph_scorer.py` | Graph scorer |
| `tests/test_eval_stories_scorer.py` | Stories scorer |
| `tests/test_eval_judge.py` | Judge helper + rubric loading |
| `tests/test_eval_brd_scorer.py` | BRD scorer |
| `tests/test_eval_design_scorer.py` | Design scorer |
| `tests/test_eval_corpus.py` | Corpus loader |
| `tests/test_eval_runner.py` | Runner (deterministic tier only — real-LLM is manual) |
| `tests/test_eval_report.py` | Report rendering |
| `tests/test_eval_cli.py` | CLI smoke tests |
| `README.md` | Append eval section |

**Conventions:**
- TDD per task: fail-first test, then implementation.
- Each task is a separate commit.
- Mocked LLM usage in tests: patch the agent or judge seam with `AsyncMock`.
- `config/settings.yaml` gets a new `eval_judge: gpt-5.4-mini` role in Task 6.

---

## Task 1: `ScoreResult` dataclass + package scaffold

**Files:**
- Create: `agent_harness/eval/__init__.py`
- Create: `agent_harness/eval/scorers/__init__.py`
- Create: `agent_harness/eval/scorers/base.py`
- Test: `tests/test_eval_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_base.py
import json
from agent_harness.eval.scorers.base import ScoreResult


def test_score_result_construct_and_serialise():
    r = ScoreResult(stage="graph", score=0.92, passed=True, threshold=0.9,
                    details={"missing_edges": [], "extra_edges": ["x->y:imports"]})
    assert r.stage == "graph"
    assert r.score == 0.92
    assert r.passed is True
    # details must be JSON-serialisable (round-trip).
    dumped = json.dumps(r.details)
    assert "extra_edges" in dumped


def test_score_result_fail_when_below_threshold():
    r = ScoreResult(stage="inventory", score=0.5, passed=False, threshold=1.0,
                    details={})
    assert r.passed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_eval_base.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 3: Create the scaffold files**

`agent_harness/eval/__init__.py`:

```python
"""Evaluation framework for the discovery pipeline."""
```

`agent_harness/eval/scorers/__init__.py`:

```python
"""Per-stage scorers."""
from .base import ScoreResult

__all__ = ["ScoreResult"]
```

`agent_harness/eval/scorers/base.py`:

```python
"""Shared dataclass for scorer output."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScoreResult:
    stage: str
    score: float
    passed: bool
    threshold: float
    details: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_eval_base.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/eval/__init__.py agent_harness/eval/scorers/__init__.py \
        agent_harness/eval/scorers/base.py tests/test_eval_base.py
git commit -m "feat(eval): scaffold eval subpackage with ScoreResult dataclass"
```

---

## Task 2: Inventory scorer

**Files:**
- Create: `agent_harness/eval/scorers/inventory.py`
- Test: `tests/test_eval_inventory_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_inventory_scorer.py
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
    """Extra modules drop score below 1.0 because we require exact match."""
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
```

- [ ] **Step 2:** Run. Expect ImportError.

- [ ] **Step 3: Implement**

```python
# agent_harness/eval/scorers/inventory.py
"""Scanner-stage scorer — exact match on module IDs."""
from __future__ import annotations

from ...discovery.artifacts import Inventory
from .base import ScoreResult

THRESHOLD = 1.0


def score(got: Inventory, expected: Inventory) -> ScoreResult:
    got_ids = {m.id for m in got.modules}
    expected_ids = {m.id for m in expected.modules}
    missing = sorted(expected_ids - got_ids)
    extra = sorted(got_ids - expected_ids)

    if not expected_ids:
        s = 1.0 if not got_ids else 0.0
    else:
        s = len(got_ids & expected_ids) / len(expected_ids)
        if extra:
            # Penalise extras by a token amount so "extra" never passes.
            s = min(s, 0.99)

    passed = not missing and not extra
    return ScoreResult(
        stage="inventory", score=s, passed=passed, threshold=THRESHOLD,
        details={"missing": missing, "extra": extra},
    )
```

- [ ] **Step 4:** `python3 -m pytest tests/test_eval_inventory_scorer.py -v` → 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/eval/scorers/inventory.py tests/test_eval_inventory_scorer.py
git commit -m "feat(eval): inventory scorer with exact-match on module IDs"
```

---

## Task 3: Graph scorer

**Files:**
- Create: `agent_harness/eval/scorers/graph.py`
- Test: `tests/test_eval_graph_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_graph_scorer.py
from agent_harness.discovery.artifacts import DependencyGraph, GraphNode, GraphEdge
from agent_harness.eval.scorers.graph import score


def _graph(nodes, edges):
    return DependencyGraph(
        nodes=[GraphNode(id=n[0], kind=n[1], attrs=n[2] if len(n) > 2 else {})
               for n in nodes],
        edges=[GraphEdge(src=e[0], dst=e[1], kind=e[2]) for e in edges],
    )


def test_identical_graphs_score_one():
    g = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource",
          {"resource_kind": "dynamodb_table"})],
        [("orders", "dynamodb_table:Orders", "writes")],
    )
    r = score(g, g)
    assert r.stage == "graph"
    assert r.score == 1.0
    assert r.passed is True


def test_missing_edge_drops_score_below_threshold():
    got = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource", {})],
        [],
    )
    expected = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource", {})],
        [("orders", "dynamodb_table:Orders", "writes")],
    )
    r = score(got, expected)
    assert r.score < r.threshold
    assert r.passed is False
    assert ["orders", "dynamodb_table:Orders", "writes"] in [
        list(e) for e in r.details["missing_edges"]
    ]


def test_missing_aws_resource_node_fails():
    got = _graph([("orders", "module", {})], [])
    expected = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource", {})],
        [],
    )
    r = score(got, expected)
    assert r.passed is False
    assert "dynamodb_table:Orders" in r.details["missing_resources"]


def test_extra_edges_counted_but_tolerated_up_to_threshold():
    got = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource", {}),
         ("sqs_queue:q", "aws_resource", {})],
        [("orders", "dynamodb_table:Orders", "writes"),
         ("orders", "sqs_queue:q", "produces"),        # extra
         ("orders", "sqs_queue:q", "produces")],       # duplicate (de-duped by set)
    )
    expected = _graph(
        [("orders", "module", {}),
         ("dynamodb_table:Orders", "aws_resource", {})],
        [("orders", "dynamodb_table:Orders", "writes")],
    )
    r = score(got, expected)
    # 1 matching + 1 extra → Jaccard = 1 / 2 = 0.5. Below 0.9 threshold.
    assert r.score < r.threshold
    assert len(r.details["extra_edges"]) == 1


def test_threshold_is_0_9():
    g = _graph([], [])
    r = score(g, g)
    assert r.threshold == 0.9
```

- [ ] **Step 2:** Run. Expect ImportError.

- [ ] **Step 3: Implement**

```python
# agent_harness/eval/scorers/graph.py
"""Grapher-stage scorer — Jaccard over edge triples + resource-node coverage."""
from __future__ import annotations

from ...discovery.artifacts import DependencyGraph
from .base import ScoreResult

THRESHOLD = 0.9


def score(got: DependencyGraph, expected: DependencyGraph) -> ScoreResult:
    got_edges = {(e.src, e.dst, e.kind) for e in got.edges}
    expected_edges = {(e.src, e.dst, e.kind) for e in expected.edges}
    inter = got_edges & expected_edges
    union = got_edges | expected_edges
    edge_score = 1.0 if not union else len(inter) / len(union)

    expected_resources = {n.id for n in expected.nodes if n.kind == "aws_resource"}
    got_resources = {n.id for n in got.nodes if n.kind == "aws_resource"}
    missing_resources = sorted(expected_resources - got_resources)

    missing_edges = [list(e) for e in sorted(expected_edges - got_edges)]
    extra_edges = [list(e) for e in sorted(got_edges - expected_edges)]

    # Penalise missing resources on top of edge Jaccard.
    s = edge_score
    if expected_resources:
        res_score = len(got_resources & expected_resources) / len(expected_resources)
        s = (edge_score + res_score) / 2

    passed = (not missing_resources) and (not missing_edges) and (not extra_edges)
    # Also allow "near perfect" with score >= threshold, even if some extras.
    if not passed and s >= THRESHOLD and not missing_resources and not missing_edges:
        passed = True

    return ScoreResult(
        stage="graph", score=s, passed=passed, threshold=THRESHOLD,
        details={
            "missing_edges": missing_edges,
            "extra_edges": extra_edges,
            "missing_resources": missing_resources,
        },
    )
```

- [ ] **Step 4:** `python3 -m pytest tests/test_eval_graph_scorer.py -v` → 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/eval/scorers/graph.py tests/test_eval_graph_scorer.py
git commit -m "feat(eval): graph scorer with Jaccard edges and resource coverage"
```

---

## Task 4: Stories scorer

**Files:**
- Create: `agent_harness/eval/scorers/stories.py`
- Test: `tests/test_eval_stories_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_stories_scorer.py
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
    # AC sub-score should be 0, dragging total down.
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
```

- [ ] **Step 2:** Run. Expect ImportError.

- [ ] **Step 3: Implement**

```python
# agent_harness/eval/scorers/stories.py
"""Stories-stage scorer — epic/count/dep-edge shape + AC coverage."""
from __future__ import annotations

from typing import Any

from ...discovery.artifacts import Stories
from .base import ScoreResult

THRESHOLD = 0.85


def score(got: Stories, expected: dict[str, Any]) -> ScoreResult:
    epic_module = {e.id: e.module_id for e in got.epics}
    story_module = {s.id: epic_module.get(s.epic_id, s.epic_id) for s in got.stories}

    # 1) Epic coverage — every expected module has ≥1 epic.
    expected_modules = set(expected.get("expected_epic_modules", []))
    got_modules_with_epics = {e.module_id for e in got.epics}
    if not expected_modules:
        epic_coverage = 1.0
    else:
        epic_coverage = len(got_modules_with_epics & expected_modules) / len(expected_modules)

    # 2) Story count per module within ±1.
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
            if abs(counts_by_mod.get(mod, 0) - want) <= 1
        )
        count_score = hits / len(expected_counts)

    # 3) Dep-edge Jaccard, projected to module → module.
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

    # 4) Acceptance-criteria coverage.
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
```

- [ ] **Step 4:** `python3 -m pytest tests/test_eval_stories_scorer.py -v` → 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/eval/scorers/stories.py tests/test_eval_stories_scorer.py
git commit -m "feat(eval): stories scorer with epic/count/dep-edge/AC sub-scores"
```

---

## Task 5: Judge helper + rubric loader

**Files:**
- Create: `agent_harness/eval/judge.py`
- Create: `agent_harness/eval/rubrics/brd.yaml`
- Create: `agent_harness/eval/rubrics/design.yaml`
- Test: `tests/test_eval_judge.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_judge.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.eval.judge import Judge, Rubric, load_rubric, JudgeScore

RUBRICS = Path(__file__).parent.parent / "agent_harness" / "eval" / "rubrics"


def test_load_rubric_brd():
    r = load_rubric("brd")
    assert r.name == "brd"
    assert r.criteria  # non-empty
    total_weight = sum(c.weight for c in r.criteria)
    assert abs(total_weight - 1.0) < 1e-6


def test_load_rubric_design():
    r = load_rubric("design")
    assert r.name == "design"
    total_weight = sum(c.weight for c in r.criteria)
    assert abs(total_weight - 1.0) < 1e-6


@pytest.mark.asyncio
async def test_judge_score_parses_valid_json():
    canned = json.dumps({
        "criteria": [
            {"name": "faithfulness", "score": 8, "reasoning": "good"},
            {"name": "resource_coverage", "score": 10, "reasoning": "all present"},
            {"name": "trigger_coverage", "score": 6, "reasoning": "one missing"},
        ],
        "overall": 8.2,
    })
    rubric = load_rubric("brd")
    judge = Judge()
    with patch("agent_harness.eval.judge._run_judge",
               new=AsyncMock(return_value=canned)):
        result = await judge.score(rubric, artifact="body", context={})
    assert isinstance(result, JudgeScore)
    assert 0.0 <= result.normalised <= 1.0
    assert result.raw_overall == 8.2


@pytest.mark.asyncio
async def test_judge_score_handles_fenced_json():
    canned = "```json\n" + json.dumps({
        "criteria": [{"name": "faithfulness", "score": 7, "reasoning": ""},
                     {"name": "resource_coverage", "score": 7, "reasoning": ""},
                     {"name": "trigger_coverage", "score": 7, "reasoning": ""}],
        "overall": 7.0,
    }) + "\n```"
    rubric = load_rubric("brd")
    judge = Judge()
    with patch("agent_harness.eval.judge._run_judge",
               new=AsyncMock(return_value=canned)):
        result = await judge.score(rubric, artifact="body", context={})
    assert result.raw_overall == 7.0


@pytest.mark.asyncio
async def test_judge_score_raises_on_garbage():
    rubric = load_rubric("brd")
    judge = Judge()
    with patch("agent_harness.eval.judge._run_judge",
               new=AsyncMock(return_value="not json at all")):
        with pytest.raises(ValueError, match="could not parse"):
            await judge.score(rubric, artifact="body", context={})


@pytest.mark.asyncio
async def test_judge_model_overridable_via_rubric():
    rubric = load_rubric("brd")
    rubric.judge_model = "gpt-5"   # override
    judge = Judge()
    captured = {}

    async def fake_runner(model, messages, temperature):
        captured["model"] = model
        return json.dumps({
            "criteria": [{"name": "faithfulness", "score": 5, "reasoning": ""},
                         {"name": "resource_coverage", "score": 5, "reasoning": ""},
                         {"name": "trigger_coverage", "score": 5, "reasoning": ""}],
            "overall": 5.0,
        })

    with patch("agent_harness.eval.judge._run_judge", side_effect=fake_runner):
        await judge.score(rubric, artifact="body", context={})
    assert captured["model"] == "gpt-5"
```

- [ ] **Step 2:** Run. Expect ImportError.

- [ ] **Step 3: Create the rubric YAMLs**

`agent_harness/eval/rubrics/brd.yaml`:

```yaml
name: brd
description: Score a module BRD for faithfulness + AWS resource coverage + trigger coverage.
judge_model: gpt-5.4-mini
temperature: 0.0
criteria:
  - name: faithfulness
    weight: 0.4
    description: Every business rule expressed in the source code is reflected in the BRD. No invented rules.
  - name: resource_coverage
    weight: 0.3
    description: Every AWS resource in the module's graph edges appears by literal name in the Side Effects section.
  - name: trigger_coverage
    weight: 0.3
    description: Every trigger present in the source (HTTP, SQS, SNS, EventBridge, DynamoDB Streams, S3, scheduled) has a bullet in the Triggers section.
```

`agent_harness/eval/rubrics/design.yaml`:

```yaml
name: design
description: Score an architect design for AWS→Azure mapping correctness + strangler-fit + IaC target.
judge_model: gpt-5.4-mini
temperature: 0.0
criteria:
  - name: mapping_correctness
    weight: 0.5
    description: Every AWS resource in State Mapping is mapped to a sensible Azure target (DynamoDB→Cosmos DB, SQS→Service Bus, SNS→Event Grid or Service Bus topic, Secrets Manager→Key Vault, EventBridge→Event Grid, Kinesis→Event Hubs, S3→Blob trigger or Event Grid).
  - name: strangler_fit
    weight: 0.3
    description: The design acknowledges the strangler-fig boundary when dependencies remain on AWS; anti-corruption-layer guidance is present where applicable.
  - name: iac_target
    weight: 0.2
    description: IaC section names Bicep (not Terraform/CloudFormation) and identifies Managed Identity for identity concerns.
```

- [ ] **Step 4: Implement the judge**

`agent_harness/eval/judge.py`:

```python
"""LLM-as-judge helper for rubric-based scoring."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel

from ..base import create_agent, run_with_retry

logger = logging.getLogger("eval.judge")

RUBRICS_DIR = Path(__file__).parent / "rubrics"


@dataclass
class Criterion:
    name: str
    weight: float
    description: str


@dataclass
class Rubric:
    name: str
    description: str
    judge_model: str
    temperature: float
    criteria: list[Criterion] = field(default_factory=list)


class _JudgeCriterion(BaseModel):
    name: str
    score: float
    reasoning: str = ""


class _JudgeResponse(BaseModel):
    criteria: list[_JudgeCriterion]
    overall: float


@dataclass
class JudgeScore:
    raw_overall: float           # 0..10
    normalised: float            # 0..1
    per_criterion: dict[str, float]
    reasoning: dict[str, str]


def load_rubric(name: str) -> Rubric:
    path = RUBRICS_DIR / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Rubric(
        name=data["name"],
        description=data.get("description", ""),
        judge_model=data.get("judge_model", "gpt-5.4-mini"),
        temperature=float(data.get("temperature", 0.0)),
        criteria=[Criterion(**c) for c in data.get("criteria", [])],
    )


async def _run_judge(model: str, messages: str, temperature: float) -> str:
    """Indirection point so tests can patch a single seam."""
    agent = create_agent(role="eval_judge", tools=[])
    return await run_with_retry(agent, messages)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


@dataclass
class Judge:
    async def score(self, rubric: Rubric, artifact: str,
                    context: dict) -> JudgeScore:
        prompt = _format_prompt(rubric, artifact, context)
        raw = await _run_judge(rubric.judge_model, prompt, rubric.temperature)
        try:
            parsed = _JudgeResponse.model_validate_json(_strip_fences(raw))
        except Exception as exc:
            raise ValueError(f"could not parse judge response: {exc}") from exc

        per_criterion = {c.name: c.score for c in parsed.criteria}
        reasoning = {c.name: c.reasoning for c in parsed.criteria}
        normalised = _weighted_normalised(parsed, rubric)
        return JudgeScore(raw_overall=parsed.overall, normalised=normalised,
                          per_criterion=per_criterion, reasoning=reasoning)


def _format_prompt(rubric: Rubric, artifact: str, context: dict) -> str:
    ctx_block = "\n".join(f"- {k}: {v}" for k, v in context.items())
    criteria_block = "\n".join(
        f"- {c.name} (weight {c.weight}): {c.description}" for c in rubric.criteria
    )
    return (
        "You are a rubric-based evaluator. Score the ARTIFACT against each CRITERION "
        "on a 0-10 scale. Return ONLY JSON (no prose, no fences):\n\n"
        '{"criteria": [{"name": "...", "score": 0-10, "reasoning": "..."}], '
        '"overall": <weighted mean, 0-10>}\n\n'
        f"RUBRIC: {rubric.name} — {rubric.description}\n"
        f"CRITERIA:\n{criteria_block}\n\n"
        f"CONTEXT:\n{ctx_block}\n\n"
        f"ARTIFACT:\n{artifact}\n"
    )


def _weighted_normalised(parsed: _JudgeResponse, rubric: Rubric) -> float:
    by_name = {c.name: c for c in parsed.criteria}
    total = 0.0
    used_weight = 0.0
    for c in rubric.criteria:
        if c.name in by_name:
            total += by_name[c.name].score * c.weight
            used_weight += c.weight
    if used_weight == 0:
        return 0.0
    return max(0.0, min(1.0, total / (10.0 * used_weight)))
```

- [ ] **Step 5:** `python3 -m pytest tests/test_eval_judge.py -v` → 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_harness/eval/judge.py agent_harness/eval/rubrics/ tests/test_eval_judge.py
git commit -m "feat(eval): LLM-as-judge helper with YAML rubric loader"
```

---

## Task 6: BRD scorer

**Files:**
- Create: `agent_harness/eval/scorers/brd.py`
- Modify: `config/settings.yaml` (add `eval_judge` role)
- Test: `tests/test_eval_brd_scorer.py`

- [ ] **Step 1: Add `eval_judge` role to `config/settings.yaml`**

Append under the existing `models:` block:

```yaml
  # ── Evaluation ──
  eval_judge: gpt-5.4-mini
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_eval_brd_scorer.py
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    DependencyGraph, GraphEdge, GraphNode, Inventory, ModuleRecord,
)
from agent_harness.eval.judge import JudgeScore
from agent_harness.eval.scorers.brd import score


def _inv():
    return Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path="orders", language="python",
                              handler_entrypoint="orders/handler.py",
                              loc=1, config_files=[])],
    )


def _graph():
    return DependencyGraph(
        nodes=[GraphNode(id="orders", kind="module", attrs={}),
               GraphNode(id="dynamodb_table:Orders", kind="aws_resource",
                         attrs={"resource_kind": "dynamodb_table"})],
        edges=[GraphEdge(src="orders", dst="dynamodb_table:Orders", kind="writes")],
    )


_GOOD_BODY = (
    "## Purpose\nx\n## Triggers\nHTTP\n## Inputs\nx\n## Outputs\nx\n"
    "## Business Rules\n- idempotent\n"
    "## Side Effects\n- writes dynamodb_table:Orders\n"
    "## Error Paths\n- returns 500\n"
    "## Non-Functionals\n- low latency\n## PII/Compliance\n- none\n"
)

_BAD_BODY = "## Purpose\nx\n"  # missing required sections


@pytest.mark.asyncio
async def test_brd_scorer_passes_when_structural_and_judge_both_pass():
    inv = _inv()
    graph = _graph()
    brd = {"orders": _GOOD_BODY}
    js = JudgeScore(raw_overall=8.0, normalised=0.8,
                     per_criterion={"faithfulness": 8, "resource_coverage": 8,
                                    "trigger_coverage": 8},
                     reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score(brd, inv, graph)
    assert r.stage == "brd"
    assert r.passed is True
    assert r.score >= r.threshold


@pytest.mark.asyncio
async def test_brd_scorer_fails_when_sections_missing():
    inv = _inv()
    graph = _graph()
    brd = {"orders": _BAD_BODY}
    js = JudgeScore(raw_overall=10.0, normalised=1.0, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score(brd, inv, graph)
    assert r.passed is False
    assert r.details["structural"]["orders"]["missing_sections"]


@pytest.mark.asyncio
async def test_brd_scorer_fails_when_module_missing_brd():
    inv = _inv()
    graph = _graph()
    brd: dict[str, str] = {}  # no BRDs at all
    js = JudgeScore(raw_overall=10.0, normalised=1.0, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score(brd, inv, graph)
    assert r.passed is False
    assert "orders" in r.details["missing_module_brds"]


@pytest.mark.asyncio
async def test_brd_scorer_fails_when_judge_scores_low():
    inv = _inv()
    graph = _graph()
    brd = {"orders": _GOOD_BODY}
    js = JudgeScore(raw_overall=2.0, normalised=0.2, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score(brd, inv, graph)
    # structural=1.0, judge=0.2 → mean=0.6 → below 0.7 threshold
    assert r.passed is False


@pytest.mark.asyncio
async def test_brd_scorer_threshold_is_0_7():
    inv = _inv()
    graph = _graph()
    js = JudgeScore(raw_overall=7.0, normalised=0.7, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score({"orders": _GOOD_BODY}, inv, graph)
    assert r.threshold == 0.7
```

- [ ] **Step 3:** Run. Expect ImportError.

- [ ] **Step 4: Implement**

```python
# agent_harness/eval/scorers/brd.py
"""BRD-stage scorer — structural + LLM-as-judge."""
from __future__ import annotations

import re
from typing import Any

from ...discovery.artifacts import DependencyGraph, Inventory
from ..judge import Judge, JudgeScore, load_rubric
from .base import ScoreResult

THRESHOLD = 0.7
REQUIRED_SECTIONS = ("Business Rules", "Error Paths", "Side Effects")


async def _judge_score(rubric, artifact: str, context: dict) -> JudgeScore:
    """Seam for tests to patch."""
    judge = Judge()
    return await judge.score(rubric, artifact, context)


async def score(brd: dict[str, str], inventory: Inventory,
                graph: DependencyGraph) -> ScoreResult:
    rubric = load_rubric("brd")

    # Structural scoring — missing modules and missing sections.
    missing_module_brds = sorted(
        [m.id for m in inventory.modules if m.id not in brd]
    )
    structural_per_module: dict[str, Any] = {}
    structural_scores: list[float] = []
    for module_id, body in brd.items():
        missing = [sec for sec in REQUIRED_SECTIONS if not _section_has_content(body, sec)]
        per = 1.0 - (len(missing) / len(REQUIRED_SECTIONS))
        structural_per_module[module_id] = {"missing_sections": missing, "score": per}
        structural_scores.append(per)
    if missing_module_brds:
        structural_scores.extend([0.0] * len(missing_module_brds))
    structural_score = (sum(structural_scores) / len(structural_scores)) \
        if structural_scores else 0.0

    # Judge scoring — one call per module BRD, averaged.
    judge_scores: list[float] = []
    judge_details: dict[str, Any] = {}
    for module_id, body in brd.items():
        edges = [f"{e.src} -[{e.kind}]-> {e.dst}" for e in graph.edges
                 if e.src == module_id or e.dst == module_id]
        js = await _judge_score(
            rubric, artifact=body,
            context={"module_id": module_id, "edges": "; ".join(edges)},
        )
        judge_scores.append(js.normalised)
        judge_details[module_id] = {"raw_overall": js.raw_overall,
                                    "per_criterion": js.per_criterion,
                                    "reasoning": js.reasoning}
    judge_score = (sum(judge_scores) / len(judge_scores)) if judge_scores else 0.0

    total = (structural_score + judge_score) / 2
    passed = total >= THRESHOLD and not missing_module_brds

    return ScoreResult(
        stage="brd", score=total, passed=passed, threshold=THRESHOLD,
        details={
            "structural": structural_per_module,
            "structural_score": structural_score,
            "missing_module_brds": missing_module_brds,
            "judge_score": judge_score,
            "judge": judge_details,
        },
    )


def _section_text(body: str, name: str) -> str:
    pattern = rf"^##\s+{re.escape(name)}\b.*?$(.*?)(?=^##\s|\Z)"
    m = re.search(pattern, body, flags=re.MULTILINE | re.DOTALL)
    return (m.group(1) if m else "").strip()


def _section_has_content(body: str, name: str) -> bool:
    text = _section_text(body, name)
    for line in text.splitlines():
        line = line.strip()
        if line and line != "- " and not line.startswith("#"):
            return True
    return False
```

- [ ] **Step 5:** `python3 -m pytest tests/test_eval_brd_scorer.py -v` → 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_harness/eval/scorers/brd.py config/settings.yaml tests/test_eval_brd_scorer.py
git commit -m "feat(eval): BRD scorer with structural + judge scoring"
```

---

## Task 7: Design scorer

**Files:**
- Create: `agent_harness/eval/scorers/design.py`
- Test: `tests/test_eval_design_scorer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_design_scorer.py
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    DependencyGraph, GraphEdge, GraphNode, Inventory, ModuleRecord,
)
from agent_harness.eval.judge import JudgeScore
from agent_harness.eval.scorers.design import score


def _inv():
    return Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path="orders", language="python",
                              handler_entrypoint="orders/handler.py",
                              loc=1, config_files=[])],
    )


def _graph():
    return DependencyGraph(
        nodes=[GraphNode(id="orders", kind="module", attrs={}),
               GraphNode(id="dynamodb_table:Orders", kind="aws_resource",
                         attrs={"resource_kind": "dynamodb_table"})],
        edges=[GraphEdge(src="orders", dst="dynamodb_table:Orders", kind="writes")],
    )


_GOOD_DESIGN = (
    "## Function Plan\nFlex\n"
    "## Trigger Bindings\n- HTTP trigger\n"
    "## State Mapping\n- dynamodb_table:Orders → Cosmos DB NoSQL\n"
    "## Secrets\n- KV\n## Identity\n- Managed Identity\n"
    "## IaC\n- Bicep\n## Observability\n- App Insights\n"
)

_BAD_DESIGN = "## Function Plan\nFlex\n"  # almost everything missing


@pytest.mark.asyncio
async def test_design_scorer_passes_when_structural_and_judge_both_pass():
    js = JudgeScore(raw_overall=8.0, normalised=0.8, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score({"orders": _GOOD_DESIGN}, _inv(), _graph())
    assert r.stage == "design"
    assert r.passed is True


@pytest.mark.asyncio
async def test_design_scorer_fails_when_sections_missing():
    js = JudgeScore(raw_overall=10.0, normalised=1.0, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score({"orders": _BAD_DESIGN}, _inv(), _graph())
    assert r.passed is False
    assert r.details["structural"]["orders"]["missing_sections"]


@pytest.mark.asyncio
async def test_design_scorer_fails_when_module_missing_design():
    js = JudgeScore(raw_overall=10.0, normalised=1.0, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score({}, _inv(), _graph())
    assert r.passed is False
    assert "orders" in r.details["missing_module_designs"]


@pytest.mark.asyncio
async def test_design_scorer_threshold_is_0_7():
    js = JudgeScore(raw_overall=7.0, normalised=0.7, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        r = await score({"orders": _GOOD_DESIGN}, _inv(), _graph())
    assert r.threshold == 0.7
```

- [ ] **Step 2:** Run. Expect ImportError.

- [ ] **Step 3: Implement**

```python
# agent_harness/eval/scorers/design.py
"""Design-stage scorer — structural + LLM-as-judge."""
from __future__ import annotations

import re
from typing import Any

from ...discovery.artifacts import DependencyGraph, Inventory
from ..judge import Judge, JudgeScore, load_rubric
from .base import ScoreResult

THRESHOLD = 0.7
REQUIRED_SECTIONS = (
    "Function Plan", "Trigger Bindings", "State Mapping",
    "Secrets", "Identity", "IaC", "Observability",
)


async def _judge_score(rubric, artifact: str, context: dict) -> JudgeScore:
    judge = Judge()
    return await judge.score(rubric, artifact, context)


async def score(design: dict[str, str], inventory: Inventory,
                graph: DependencyGraph) -> ScoreResult:
    rubric = load_rubric("design")

    missing_module_designs = sorted(
        [m.id for m in inventory.modules if m.id not in design]
    )
    structural_per_module: dict[str, Any] = {}
    structural_scores: list[float] = []
    for module_id, body in design.items():
        missing = [sec for sec in REQUIRED_SECTIONS if not _section_has_content(body, sec)]
        per = 1.0 - (len(missing) / len(REQUIRED_SECTIONS))
        structural_per_module[module_id] = {"missing_sections": missing, "score": per}
        structural_scores.append(per)
    if missing_module_designs:
        structural_scores.extend([0.0] * len(missing_module_designs))
    structural_score = (sum(structural_scores) / len(structural_scores)) \
        if structural_scores else 0.0

    judge_scores: list[float] = []
    judge_details: dict[str, Any] = {}
    for module_id, body in design.items():
        edges = [f"{e.src} -[{e.kind}]-> {e.dst}" for e in graph.edges
                 if e.src == module_id or e.dst == module_id]
        js = await _judge_score(
            rubric, artifact=body,
            context={"module_id": module_id, "edges": "; ".join(edges)},
        )
        judge_scores.append(js.normalised)
        judge_details[module_id] = {"raw_overall": js.raw_overall,
                                    "per_criterion": js.per_criterion,
                                    "reasoning": js.reasoning}
    judge_score = (sum(judge_scores) / len(judge_scores)) if judge_scores else 0.0

    total = (structural_score + judge_score) / 2
    passed = total >= THRESHOLD and not missing_module_designs

    return ScoreResult(
        stage="design", score=total, passed=passed, threshold=THRESHOLD,
        details={
            "structural": structural_per_module,
            "structural_score": structural_score,
            "missing_module_designs": missing_module_designs,
            "judge_score": judge_score,
            "judge": judge_details,
        },
    )


def _section_text(body: str, name: str) -> str:
    pattern = rf"^##\s+{re.escape(name)}\b.*?$(.*?)(?=^##\s|\Z)"
    m = re.search(pattern, body, flags=re.MULTILINE | re.DOTALL)
    return (m.group(1) if m else "").strip()


def _section_has_content(body: str, name: str) -> bool:
    text = _section_text(body, name)
    for line in text.splitlines():
        line = line.strip()
        if line and line != "- " and not line.startswith("#"):
            return True
    return False
```

- [ ] **Step 4:** `python3 -m pytest tests/test_eval_design_scorer.py -v` → 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/eval/scorers/design.py tests/test_eval_design_scorer.py
git commit -m "feat(eval): design scorer with structural + judge scoring"
```

---

## Task 8: Corpus loader + synthetic fixture + canned responses

**Files:**
- Create: `agent_harness/eval/corpus.py`
- Create: `tests/eval_corpus/synthetic/corpus.yaml`
- Create: `tests/eval_corpus/synthetic/expected_inventory.json`
- Create: `tests/eval_corpus/synthetic/expected_graph.json`
- Create: `tests/eval_corpus/synthetic/expected_stories_shape.json`
- Create: `tests/eval_corpus/synthetic/canned/inventory.json`
- Create: `tests/eval_corpus/synthetic/canned/graph.json` (empty LLM response; deterministic path fills it)
- Create: `tests/eval_corpus/synthetic/canned/brd_orders.md` through `brd_notifications.md`
- Create: `tests/eval_corpus/synthetic/canned/design_orders.md` through `design_notifications.md`
- Create: `tests/eval_corpus/synthetic/canned/system_brd.md`
- Create: `tests/eval_corpus/synthetic/canned/system_design.md`
- Create: `tests/eval_corpus/synthetic/canned/stories.json`
- Test: `tests/test_eval_corpus.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_corpus.py
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
```

- [ ] **Step 2:** Run. Expect ImportError.

- [ ] **Step 3: Create `tests/eval_corpus/synthetic/corpus.yaml`:**

```yaml
name: synthetic
repo_path: ../../fixtures/synthetic_repo
description: Three-module Lambda fixture used by discovery unit tests.
```

- [ ] **Step 4: Create `tests/eval_corpus/synthetic/expected_inventory.json`:**

```json
{
  "repo_meta": {
    "root_path": "tests/fixtures/synthetic_repo",
    "total_files": 8,
    "total_loc": 60,
    "discovered_at": "2026-04-14T00:00:00Z"
  },
  "modules": [
    {"id": "orders",        "path": "orders",        "language": "python",
     "handler_entrypoint": "orders/handler.py",        "loc": 14, "config_files": ["orders/requirements.txt"]},
    {"id": "payments",      "path": "payments",      "language": "python",
     "handler_entrypoint": "payments/handler.py",      "loc": 18, "config_files": ["payments/requirements.txt"]},
    {"id": "notifications", "path": "notifications", "language": "python",
     "handler_entrypoint": "notifications/handler.py", "loc": 12, "config_files": ["notifications/requirements.txt"]}
  ]
}
```

- [ ] **Step 5: Create `tests/eval_corpus/synthetic/expected_graph.json`:**

```json
{
  "nodes": [
    {"id": "orders",        "kind": "module",       "attrs": {"path": "orders",        "language": "python"}},
    {"id": "payments",      "kind": "module",       "attrs": {"path": "payments",      "language": "python"}},
    {"id": "notifications", "kind": "module",       "attrs": {"path": "notifications", "language": "python"}},
    {"id": "dynamodb_table:Orders",            "kind": "aws_resource",
     "attrs": {"resource_kind": "dynamodb_table",            "resource_name": "Orders"}},
    {"id": "dynamodb_table:Payments",          "kind": "aws_resource",
     "attrs": {"resource_kind": "dynamodb_table",            "resource_name": "Payments"}},
    {"id": "sqs_queue:payments-queue",         "kind": "aws_resource",
     "attrs": {"resource_kind": "sqs_queue",                 "resource_name": "payments-queue"}},
    {"id": "sns_topic:payment-events",         "kind": "aws_resource",
     "attrs": {"resource_kind": "sns_topic",                 "resource_name": "payment-events"}},
    {"id": "secrets_manager_secret:webhook/url", "kind": "aws_resource",
     "attrs": {"resource_kind": "secrets_manager_secret",    "resource_name": "webhook/url"}}
  ],
  "edges": [
    {"src": "orders",        "dst": "dynamodb_table:Orders",              "kind": "writes"},
    {"src": "orders",        "dst": "sqs_queue:payments-queue",           "kind": "produces"},
    {"src": "payments",      "dst": "dynamodb_table:Orders",              "kind": "reads"},
    {"src": "payments",      "dst": "dynamodb_table:Payments",            "kind": "writes"},
    {"src": "payments",      "dst": "sns_topic:payment-events",           "kind": "produces"},
    {"src": "notifications", "dst": "secrets_manager_secret:webhook/url", "kind": "reads"}
  ]
}
```

- [ ] **Step 6: Create `tests/eval_corpus/synthetic/expected_stories_shape.json`:**

```json
{
  "expected_epic_modules": ["orders", "payments", "notifications"],
  "expected_story_count_per_module": {"orders": 1, "payments": 1, "notifications": 1},
  "expected_dep_edges": [["payments", "orders"], ["notifications", "payments"]]
}
```

- [ ] **Step 7: Create the canned directory.** These mirror the responses used in the existing `test_discovery_e2e.py`. Put each on disk; the runner (Task 9) will load them.

`tests/eval_corpus/synthetic/canned/inventory.json` — valid JSON: copy the same 3-module content from `expected_inventory.json`.

`tests/eval_corpus/synthetic/canned/graph.json` — content is literally `[]` (the grapher's LLM fallback responds with empty JSON array; the deterministic code path produces the graph from tree-sitter).

`tests/eval_corpus/synthetic/canned/brd_orders.md`:

```
## Purpose
Receives orders.
## Triggers
- API Gateway POST /orders.
## Inputs
JSON body.
## Outputs
201 + order id.
## Business Rules
- Idempotent on order id.
## Side Effects
- writes dynamodb_table:Orders
- produces sqs_queue:payments-queue
## Error Paths
- returns 500 on DynamoDB failure.
## Non-Functionals
- p95 < 200ms.
## PII/Compliance
- Payment-related PII flagged for retention policy.
```

`tests/eval_corpus/synthetic/canned/brd_payments.md`:

```
## Purpose
Processes payments.
## Triggers
- SQS: payments-queue
## Inputs
Message with order id.
## Outputs
Payment record.
## Business Rules
- One payment per order.
## Side Effects
- reads dynamodb_table:Orders
- writes dynamodb_table:Payments
- produces sns_topic:payment-events
## Error Paths
- retries on transient failure.
## Non-Functionals
- Ordering preserved per-order.
## PII/Compliance
- No PAN stored.
```

`tests/eval_corpus/synthetic/canned/brd_notifications.md`:

```
## Purpose
Sends notifications.
## Triggers
- SNS: payment-events
## Inputs
SNS record.
## Outputs
Webhook POST.
## Business Rules
- Retry on webhook failure.
## Side Effects
- reads secrets_manager_secret:webhook/url
## Error Paths
- dead-letter after 3 retries.
## Non-Functionals
- Best-effort delivery.
## PII/Compliance
- Webhook URL is a secret.
```

`tests/eval_corpus/synthetic/canned/system_brd.md`:

```
# System BRD
Cross-module flow: orders → payments → notifications.
```

`tests/eval_corpus/synthetic/canned/design_orders.md`:

```
## Function Plan
Flex consumption.
## Trigger Bindings
- HTTP trigger.
## State Mapping
- dynamodb_table:Orders → Cosmos DB NoSQL container Orders.
- sqs_queue:payments-queue → Service Bus queue payments-queue.
## Secrets
- Cosmos key in Key Vault.
## Identity
- Managed Identity.
## IaC
- Bicep.
## Observability
- App Insights.
```

`tests/eval_corpus/synthetic/canned/design_payments.md`:

```
## Function Plan
Premium.
## Trigger Bindings
- Service Bus queue trigger.
## State Mapping
- dynamodb_table:Orders → Cosmos DB NoSQL Orders.
- dynamodb_table:Payments → Cosmos DB NoSQL Payments.
- sns_topic:payment-events → Event Grid topic.
## Secrets
- Cosmos key in Key Vault.
## Identity
- Managed Identity.
## IaC
- Bicep.
## Observability
- App Insights.
```

`tests/eval_corpus/synthetic/canned/design_notifications.md`:

```
## Function Plan
Consumption.
## Trigger Bindings
- Event Grid trigger.
## State Mapping
- secrets_manager_secret:webhook/url → Key Vault secret webhook-url.
## Secrets
- Key Vault.
## Identity
- Managed Identity.
## IaC
- Bicep.
## Observability
- App Insights.
```

`tests/eval_corpus/synthetic/canned/system_design.md`:

```
# System Design
Strangler-fig: orders first, then payments, then notifications.
```

`tests/eval_corpus/synthetic/canned/stories.json`:

```json
{
  "epics": [
    {"id": "E1", "module_id": "orders",        "title": "Migrate orders",        "story_ids": ["S1"]},
    {"id": "E2", "module_id": "payments",      "title": "Migrate payments",      "story_ids": ["S2"]},
    {"id": "E3", "module_id": "notifications", "title": "Migrate notifications", "story_ids": ["S3"]}
  ],
  "stories": [
    {"id": "S1", "epic_id": "E1", "title": "orders fn",        "description": "d",
     "acceptance_criteria": [{"text": "ac"}], "depends_on": [],        "blocks": ["S2"], "estimate": "M"},
    {"id": "S2", "epic_id": "E2", "title": "payments fn",      "description": "d",
     "acceptance_criteria": [{"text": "ac"}], "depends_on": ["S1"],    "blocks": ["S3"], "estimate": "M"},
    {"id": "S3", "epic_id": "E3", "title": "notifications fn", "description": "d",
     "acceptance_criteria": [{"text": "ac"}], "depends_on": ["S2"],    "blocks": [],     "estimate": "M"}
  ]
}
```

- [ ] **Step 8: Implement `agent_harness/eval/corpus.py`:**

```python
"""Corpus loader — reads tests/eval_corpus/<name>/*."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..discovery.artifacts import DependencyGraph, Inventory

CORPUS_ROOT = Path(__file__).parent.parent.parent / "tests" / "eval_corpus"


@dataclass
class Corpus:
    name: str
    repo_path: Path
    expected_inventory: Inventory
    expected_graph: DependencyGraph
    expected_stories: dict[str, Any]
    canned_dir: Path


def load_corpus(name: str) -> Corpus:
    base = CORPUS_ROOT / name
    if not base.is_dir():
        raise FileNotFoundError(f"corpus {name!r} not found under {CORPUS_ROOT}")

    meta = yaml.safe_load((base / "corpus.yaml").read_text(encoding="utf-8"))
    repo_path = (base / meta["repo_path"]).resolve()

    inv = Inventory.model_validate_json(
        (base / "expected_inventory.json").read_text(encoding="utf-8")
    )
    graph = DependencyGraph.model_validate_json(
        (base / "expected_graph.json").read_text(encoding="utf-8")
    )
    stories = json.loads(
        (base / "expected_stories_shape.json").read_text(encoding="utf-8")
    )
    return Corpus(
        name=meta["name"], repo_path=repo_path,
        expected_inventory=inv, expected_graph=graph,
        expected_stories=stories, canned_dir=base / "canned",
    )
```

- [ ] **Step 9:** `python3 -m pytest tests/test_eval_corpus.py -v` → 2 PASS.

- [ ] **Step 10: Commit**

```bash
git add agent_harness/eval/corpus.py tests/eval_corpus/ tests/test_eval_corpus.py
git commit -m "feat(eval): corpus loader + synthetic corpus with expected outputs + canned LLM responses"
```

---

## Task 9: Runner — deterministic and real-LLM tiers

**Files:**
- Create: `agent_harness/eval/runner.py`
- Test: `tests/test_eval_runner.py`

- [ ] **Step 1: Write the failing test (deterministic tier only)**

```python
# tests/test_eval_runner.py
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
```

- [ ] **Step 2:** Run. Expect ImportError.

- [ ] **Step 3: Implement**

```python
# agent_harness/eval/runner.py
"""Run the discovery pipeline against a corpus under a chosen tier."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, patch

from ..discovery import paths as discovery_paths
from ..discovery.artifacts import DependencyGraph, Inventory, Stories
from ..discovery.workflow import run_discovery
from ..persistence.repository import MigrationRepository
from .corpus import Corpus

Tier = Literal["deterministic", "real_llm"]


@dataclass
class RunArtifacts:
    inventory: Inventory
    graph: DependencyGraph
    brd: dict[str, str]
    design: dict[str, str]
    stories: Stories
    run_dir: Path


async def run_corpus(corpus: Corpus, tier: Tier,
                     repo: MigrationRepository,
                     repo_id: str | None = None) -> RunArtifacts:
    if tier not in ("deterministic", "real_llm"):
        raise ValueError(f"unknown tier: {tier!r}")

    repo_id = repo_id or f"eval-{corpus.name}"
    if tier == "real_llm":
        await run_discovery(repo_id=repo_id, repo_path=str(corpus.repo_path),
                            repo=repo)
    else:
        canned = _load_canned(corpus)
        with patch("agent_harness.discovery.repo_scanner._run_agent",
                   new=AsyncMock(return_value=canned["inventory"])), \
             patch("agent_harness.discovery.dependency_grapher._run_agent",
                   new=AsyncMock(return_value=canned["graph"])), \
             patch("agent_harness.discovery.brd_extractor._run_module_agent",
                   side_effect=_module_side_effect(canned["brd"])), \
             patch("agent_harness.discovery.brd_extractor._run_system_agent",
                   new=AsyncMock(return_value=canned["system_brd"])), \
             patch("agent_harness.discovery.architect._run_module_agent",
                   side_effect=_module_side_effect(canned["design"])), \
             patch("agent_harness.discovery.architect._run_system_agent",
                   new=AsyncMock(return_value=canned["system_design"])), \
             patch("agent_harness.discovery.story_decomposer._run_agent",
                   new=AsyncMock(return_value=canned["stories"])):
            await run_discovery(repo_id=repo_id, repo_path=str(corpus.repo_path),
                                repo=repo)

    # Load artifacts back from disk.
    inv = Inventory.model_validate_json(
        discovery_paths.inventory_path(repo_id).read_text(encoding="utf-8")
    )
    graph = DependencyGraph.model_validate_json(
        discovery_paths.graph_path(repo_id).read_text(encoding="utf-8")
    )
    brd_dir = discovery_paths.brd_dir(repo_id)
    brd = {p.stem: p.read_text(encoding="utf-8") for p in brd_dir.glob("*.md")
           if not p.stem.startswith("_")}
    design_dir = discovery_paths.design_dir(repo_id)
    design = {p.stem: p.read_text(encoding="utf-8") for p in design_dir.glob("*.md")
              if not p.stem.startswith("_")}
    stories = Stories.model_validate_json(
        discovery_paths.stories_path(repo_id).read_text(encoding="utf-8")
    )
    return RunArtifacts(
        inventory=inv, graph=graph, brd=brd, design=design,
        stories=stories, run_dir=discovery_paths.repo_dir(repo_id),
    )


def _load_canned(corpus: Corpus) -> dict:
    base = corpus.canned_dir
    brd = {p.stem[len("brd_"):]: p.read_text(encoding="utf-8")
           for p in base.glob("brd_*.md")}
    design = {p.stem[len("design_"):]: p.read_text(encoding="utf-8")
              for p in base.glob("design_*.md")}
    return {
        "inventory":     (base / "inventory.json").read_text(encoding="utf-8"),
        "graph":         (base / "graph.json").read_text(encoding="utf-8"),
        "brd":           brd,
        "system_brd":    (base / "system_brd.md").read_text(encoding="utf-8"),
        "design":        design,
        "system_design": (base / "system_design.md").read_text(encoding="utf-8"),
        "stories":       (base / "stories.json").read_text(encoding="utf-8"),
    }


def _module_side_effect(per_module: dict[str, str]):
    async def _fn(message: str) -> str:
        for mid, body in per_module.items():
            if f"`{mid}`" in message:
                return body
        return next(iter(per_module.values()))  # fallback
    return _fn
```

- [ ] **Step 4:** `python3 -m pytest tests/test_eval_runner.py -v` → 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/eval/runner.py tests/test_eval_runner.py
git commit -m "feat(eval): runner with deterministic + real_llm tiers"
```

---

## Task 10: Report rendering

**Files:**
- Create: `agent_harness/eval/report.py`
- Test: `tests/test_eval_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_report.py
import json
from pathlib import Path

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
    # Format: <timestamp>-<corpus>
    assert bundle.run_dir.name.endswith("-synthetic")
    assert bundle.run_dir.parent == tmp_path
```

- [ ] **Step 2:** Run. Expect ImportError.

- [ ] **Step 3: Implement**

```python
# agent_harness/eval/report.py
"""Aggregate ScoreResults into a run directory with JSON + markdown."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from .scorers.base import ScoreResult


@dataclass
class ReportBundle:
    corpus: str
    tier: str
    overall_passed: bool
    per_stage: dict[str, ScoreResult]
    run_dir: Path


def render(results: list[ScoreResult], corpus_name: str, tier: str,
           out_dir: Path) -> ReportBundle:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(out_dir) / f"{timestamp}-{corpus_name}"
    run_dir.mkdir(parents=True, exist_ok=True)

    overall_passed = all(r.passed for r in results)
    per_stage = {r.stage: r for r in results}

    # JSON
    payload = {
        "corpus": corpus_name,
        "tier": tier,
        "overall_passed": overall_passed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": [asdict(r) for r in results],
    }
    (run_dir / "report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    # Markdown
    verdict = "PASS" if overall_passed else "FAIL"
    lines = [
        f"# Eval report: {corpus_name} ({tier}) — {verdict}",
        "",
        "| Stage | Score | Threshold | Passed |",
        "|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.stage} | {r.score:.3f} | {r.threshold:.3f} | "
            f"{'✅' if r.passed else '❌'} |"
        )
    lines.append("")
    for r in results:
        lines.append(f"## {r.stage}")
        lines.append("```json")
        lines.append(json.dumps(r.details, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
    (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

    return ReportBundle(
        corpus=corpus_name, tier=tier, overall_passed=overall_passed,
        per_stage=per_stage, run_dir=run_dir,
    )
```

- [ ] **Step 4:** `python3 -m pytest tests/test_eval_report.py -v` → 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/eval/report.py tests/test_eval_report.py
git commit -m "feat(eval): report rendering (JSON + markdown) with per-stage table"
```

---

## Task 11: CLI

**Files:**
- Create: `agent_harness/eval/__main__.py`
- Modify: `agent_harness/eval/__init__.py` (expose public API)
- Test: `tests/test_eval_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_cli.py
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.eval.__main__ import main


@pytest.mark.asyncio
async def test_cli_run_deterministic_exits_zero_on_pass(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    # Patch the judge so BRD/design scoring passes deterministically.
    from agent_harness.eval.judge import JudgeScore
    js = JudgeScore(raw_overall=8.0, normalised=0.8, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)), \
         patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        code = await main(["run", "--corpus", "synthetic", "--tier", "deterministic",
                           "--out", str(tmp_path / "out")])
    assert code == 0
    # At least one run dir created.
    assert any((tmp_path / "out").iterdir())


@pytest.mark.asyncio
async def test_cli_run_unknown_corpus_exits_two(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = await main(["run", "--corpus", "does-not-exist",
                       "--tier", "deterministic", "--out", str(tmp_path / "out")])
    assert code == 2


@pytest.mark.asyncio
async def test_cli_run_exits_one_on_stage_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from agent_harness.eval.judge import JudgeScore
    # Judge returns very low score → BRD+design below threshold → exit 1.
    js = JudgeScore(raw_overall=0.0, normalised=0.0, per_criterion={}, reasoning={})
    with patch("agent_harness.eval.scorers.brd._judge_score",
               new=AsyncMock(return_value=js)), \
         patch("agent_harness.eval.scorers.design._judge_score",
               new=AsyncMock(return_value=js)):
        code = await main(["run", "--corpus", "synthetic", "--tier", "deterministic",
                           "--out", str(tmp_path / "out")])
    assert code == 1
```

- [ ] **Step 2:** Run. Expect ImportError.

- [ ] **Step 3: Implement the CLI**

`agent_harness/eval/__main__.py`:

```python
"""Eval CLI: python -m agent_harness.eval run|report ..."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from ..persistence.repository import MigrationRepository
from .corpus import load_corpus, CORPUS_ROOT
from .report import render
from .runner import run_corpus
from .scorers import inventory as inv_scorer
from .scorers import graph as graph_scorer
from .scorers import stories as stories_scorer
from .scorers import brd as brd_scorer
from .scorers import design as design_scorer


async def _run_one(corpus_name: str, tier: str, out_dir: Path) -> int:
    try:
        corpus = load_corpus(corpus_name)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    repo = MigrationRepository(db_path=out_dir / "_migration.db")
    repo.initialize()
    try:
        artifacts = await run_corpus(corpus=corpus, tier=tier, repo=repo)
    except Exception as exc:
        print(f"ERROR: pipeline crash: {exc!r}", file=sys.stderr)
        return 2

    results = [
        inv_scorer.score(artifacts.inventory, corpus.expected_inventory),
        graph_scorer.score(artifacts.graph, corpus.expected_graph),
        stories_scorer.score(artifacts.stories, corpus.expected_stories),
        await brd_scorer.score(artifacts.brd, corpus.expected_inventory, artifacts.graph),
        await design_scorer.score(artifacts.design, corpus.expected_inventory, artifacts.graph),
    ]
    bundle = render(results, corpus_name=corpus_name, tier=tier, out_dir=out_dir)
    print(f"Report: {bundle.run_dir}")
    return 0 if bundle.overall_passed else 1


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_harness.eval")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("--corpus", default=None,
                        help="Corpus name under tests/eval_corpus/. Defaults to all.")
    p_run.add_argument("--tier", choices=["deterministic", "real_llm"],
                        default="real_llm")
    p_run.add_argument("--out", default="eval-results", type=Path)

    p_report = sub.add_parser("report")
    p_report.add_argument("run_dir", type=Path)

    ns = parser.parse_args(argv)

    if ns.cmd == "report":
        md = (ns.run_dir / "report.md")
        if not md.exists():
            print(f"ERROR: no report at {md}", file=sys.stderr)
            return 2
        print(md.read_text(encoding="utf-8"))
        return 0

    # run
    out_dir = Path(ns.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if ns.corpus:
        return await _run_one(ns.corpus, ns.tier, out_dir)

    overall = 0
    for entry in sorted(Path(CORPUS_ROOT).iterdir()):
        if not entry.is_dir():
            continue
        code = await _run_one(entry.name, ns.tier, out_dir)
        if code > overall:
            overall = code
    return overall


def _entrypoint() -> None:
    code = asyncio.run(main(sys.argv[1:]))
    raise SystemExit(code)


if __name__ == "__main__":
    _entrypoint()
```

- [ ] **Step 4: Update `agent_harness/eval/__init__.py`** to expose the public API:

```python
"""Evaluation framework for the discovery pipeline.

Public API:
- load_corpus(name) -> Corpus
- run_corpus(corpus, tier, repo) -> RunArtifacts
- render(results, corpus_name, tier, out_dir) -> ReportBundle
"""
from .corpus import Corpus, load_corpus
from .report import ReportBundle, render
from .runner import RunArtifacts, run_corpus

__all__ = [
    "Corpus", "load_corpus",
    "RunArtifacts", "run_corpus",
    "ReportBundle", "render",
]
```

- [ ] **Step 5:** `python3 -m pytest tests/test_eval_cli.py -v` → 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_harness/eval/__main__.py agent_harness/eval/__init__.py tests/test_eval_cli.py
git commit -m "feat(eval): CLI with run and report subcommands"
```

---

## Task 12: Add `aws_legacy` corpus (without expected files)

**Files:**
- Create: `tests/eval_corpus/aws_legacy/corpus.yaml`
- Test: existing `tests/test_eval_corpus.py` (no new tests — loader test for non-synthetic corpus is optional; the synthetic load path exercises all the code)

This task stages a second corpus stub so the CLI's all-corpora mode sees it. Expected files are NOT hand-authored here — that's a follow-up once you've run the real-LLM tier once and reviewed output. For now the corpus carries placeholder expected files that match whatever the real-LLM produced so the CLI doesn't crash; you'll replace them after reviewing.

- [ ] **Step 1: Create `tests/eval_corpus/aws_legacy/corpus.yaml`:**

```yaml
name: aws_legacy
repo_path: ../../../../aws_legacy/generated_code
description: Real-world Python Lambda package with 4 handlers + shared services.
```

- [ ] **Step 2: Create `tests/eval_corpus/aws_legacy/expected_inventory.json` placeholder:**

Run the real-LLM scanner once via `python -m agent_harness.eval run --corpus=aws_legacy --tier=real_llm` to generate a baseline, then hand-author the expected inventory. For v1 of this task, a minimal placeholder that prevents load errors:

```json
{
  "repo_meta": {
    "root_path": "aws_legacy/generated_code",
    "total_files": 0,
    "total_loc": 0,
    "discovered_at": "2026-04-14T00:00:00Z"
  },
  "modules": []
}
```

- [ ] **Step 3: Create `tests/eval_corpus/aws_legacy/expected_graph.json`:**

```json
{"nodes": [], "edges": []}
```

- [ ] **Step 4: Create `tests/eval_corpus/aws_legacy/expected_stories_shape.json`:**

```json
{
  "expected_epic_modules": [],
  "expected_story_count_per_module": {},
  "expected_dep_edges": []
}
```

- [ ] **Step 5: Document the next step in `tests/eval_corpus/aws_legacy/README.md`:**

```markdown
# aws_legacy corpus

Placeholder expected files. Before this corpus gives meaningful regression signal:

1. Run once: `python -m agent_harness.eval run --corpus=aws_legacy --tier=real_llm`
2. Inspect the generated inventory / graph / stories under `discovery/eval-aws_legacy/`.
3. Hand-review and copy into `expected_inventory.json`, `expected_graph.json`,
   `expected_stories_shape.json`, replacing the placeholders above.
4. Author `canned/*` if you need a deterministic tier for this corpus.

Until step 3 is done, `expected_inventory.modules: []` makes every run trivially
pass the inventory/graph/stories scorers. That's intentional — the corpus is
staged but not yet wired as a regression gate.
```

- [ ] **Step 6: Commit**

```bash
git add tests/eval_corpus/aws_legacy/
git commit -m "feat(eval): stage aws_legacy corpus with placeholder expected files"
```

---

## Task 13: README section

**Files:**
- Modify: `ms-agent-harness/README.md`

- [ ] **Step 1: Append a new section**

```markdown
## Evaluation framework

Regression-detect the discovery pipeline against golden corpora.

- `python -m agent_harness.eval run --corpus=synthetic --tier=deterministic` — fast,
  no LLM calls, scores the canned pipeline output.
- `python -m agent_harness.eval run --tier=real_llm` — runs the live pipeline
  against every corpus under `tests/eval_corpus/`. Costs ~$0.10–$1/run.
- `python -m agent_harness.eval report <run_dir>` — prints the markdown report.

Each run lands at `eval-results/<timestamp>-<corpus>/report.{json,md}`. Exit code
is `0` if every stage passes its threshold, `1` if any fail, `2` on setup error.

Stage scoring:
- `inventory` — exact-match on module IDs, threshold 1.0.
- `graph` — Jaccard on edge triples + AWS resource coverage, threshold 0.9.
- `stories` — epic/count/dep-edge/AC sub-scores averaged, threshold 0.85.
- `brd` — structural (required sections) + LLM-as-judge rubric, threshold 0.7.
- `design` — structural + LLM-as-judge rubric, threshold 0.7.

Rubrics live at `agent_harness/eval/rubrics/*.yaml`. Each rubric declares its
judge model (defaults to `gpt-5.4-mini`); override per-rubric without code
changes.

To add a corpus: drop `tests/eval_corpus/<name>/corpus.yaml` + expected JSONs +
optional `canned/*` responses. See `tests/eval_corpus/aws_legacy/README.md`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(eval): document eval framework commands and scoring"
```

---

## Self-Review Notes

- **Spec coverage:**
  - §3.2 package layout — Tasks 1, 5, 9, 10, 11.
  - §4.1 corpus loader — Task 8.
  - §4.2 runner — Task 9.
  - §4.3 scorers — Tasks 2, 3, 4, 6, 7.
  - §4.4 judge — Task 5.
  - §4.5 report — Task 10.
  - §4.6 CLI — Task 11.
  - §5.1 expected_stories_shape semantics — Task 4 test `test_dep_edge_shape_compared_on_modules_not_story_ids` + Task 8 fixture.
  - §6.2 deterministic tier via canned responses — Task 8 (canned dir) + Task 9 (runner patches).
  - §6.3 corpus authoring workflow — Task 12 plus the `aws_legacy/README.md`.
  - §7 error handling — covered by Task 9 (`ValueError` on bad tier), Task 5 (judge parse failure), Task 11 (exit codes 0/1/2), Task 8 (missing corpus).
  - §8 testing — each task ships its own unit tests.
- **Placeholder scan:** None. The `aws_legacy` expected files are explicitly called "placeholder" with a documented workflow to replace them (Task 12 step 5); this is intentional staging, not a planning hole.
- **Type consistency:**
  - `ScoreResult` signature matches across all scorers (`stage`, `score`, `passed`, `threshold`, `details`).
  - `JudgeScore` fields (`raw_overall`, `normalised`, `per_criterion`, `reasoning`) consistent between Task 5 and Tasks 6/7.
  - `RunArtifacts` field list (`inventory`, `graph`, `brd`, `design`, `stories`, `run_dir`) consistent between Task 9 and Task 11.
  - `Rubric` / `Criterion` shape matches the YAML in Task 5 (name/weight/description).
  - Thresholds referenced in tests match the module constants:
    inventory=1.0, graph=0.9, stories=0.85, brd=0.7, design=0.7.
- **Back-compat:** No changes to existing discovery/orchestrator/fanout code paths. `config/settings.yaml` gains one role; `load_prompt` already falls back to a stub message when a role's prompt file is missing, so no prompt file is needed for the judge.
