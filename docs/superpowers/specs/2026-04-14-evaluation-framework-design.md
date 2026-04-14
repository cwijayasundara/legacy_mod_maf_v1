# Evaluation Framework (Sub-project C) — Design Spec

**Date:** 2026-04-14
**Status:** Draft — pending review
**Target repo:** `ms-agent-harness`
**Depends on:** `2026-04-14-discovery-planning-layer-design.md` (sub-project A) and
  `2026-04-14-migration-fanout-design.md` (sub-project B), both merged.

---

## 1. Context

Sub-project A (Discovery & Planning) and sub-project B (Fanout) together form a
pipeline with five LLM stages: scanner, grapher, BRD, architect, stories. Each
stage's correctness is currently defended by:

- Deterministic critics (`graph_critic`, `brd_critic`, `design_critic`,
  `story_critic`) + a `sanity_check` on the scanner, run inside the self-heal
  loop.
- Mocked-LLM unit and integration tests.

What's missing:

1. **Regression detection on real LLM output.** A prompt edit, a model swap,
   or a refactor to a critic can degrade pipeline quality without tripping any
   deterministic check. The existing tests mock the LLM so they don't move
   when the LLM does.
2. **Coverage across realistic repo layouts.** The synthetic 3-module fixture
   catches structural issues but not layout diversity. A shared-package
   layout (e.g. `handlers/*.py` + `services/`) exercises different code paths
   in the grapher and wave-scheduler.
3. **Qualitative scoring on free-form stages.** BRD and architect outputs are
   markdown. Deterministic critics only check section presence; they cannot
   judge whether the content is faithful to the source.

This spec introduces a regression-focused evaluation framework that runs real
discovery against golden corpora, scores every stage's output, and fails the
run if any stage drops below its threshold.

## 2. Scope

### In scope (v1)

- New `agent_harness/eval/` subpackage.
- Two corpora under `tests/eval_corpus/`:
  - `synthetic` — the existing 3-module fixture.
  - `aws_legacy` — the user's real-world layout at `aws_legacy/generated_code/`.
- Hand-authored expected outputs per corpus: `expected_inventory.json`,
  `expected_graph.json`, `expected_stories_shape.json`.
- Five stage scorers (scanner, grapher, stories, brd, design).
- LLM-as-judge helper with rubric YAML files for the two free-form stages.
- Two execution tiers: deterministic (reuses mocked-LLM fixtures from existing
  tests) and real-LLM (runs the live pipeline).
- CLI entry point `python -m agent_harness.eval ...` with `run` and `report`
  subcommands.
- JSON + markdown report artifacts under `eval-results/<timestamp>-<corpus>/`.
- Exit-code gating: 0 if every scored stage passes its threshold, 1 otherwise.
- Unit tests for every scorer + judge + runner + report layer.

### Out of scope (future C.2+)

- Trending / dashboard over historical runs.
- Cross-model comparison UI.
- CI GitHub Action wiring (infrastructure; trivial once v1 lands).
- Judge ensembling, active-learning fixture generation, automated golden-set
  maintenance.
- Additional corpora beyond the two above.
- Evaluation of the migrate / review / security stages — this spec covers
  discovery only. Migration-pipeline evaluation is a separate future cycle.

## 3. Architecture

### 3.1 Two tiers, one set of scorers

| Tier | Input source | LLM calls | Cost | When |
|---|---|---|---|---|
| `deterministic` | Canned responses from the existing mocked-LLM tests | None | 0 | Every commit / default CI |
| `real_llm` | Live pipeline invocation on each corpus repo | ~8 per stage × 5 stages × N corpora | ~$0.10–$1/run | Manual / nightly |

Same scorers run on both tiers. The only difference is where the artifacts
come from — the runner either mocks `_run_agent` with canned responses or lets
it hit the real model.

### 3.2 Placement

```
ms-agent-harness/
└── agent_harness/
    └── eval/                          [NEW]
        ├── __init__.py
        ├── __main__.py                CLI: run, report
        ├── corpus.py                  Corpus model + loader
        ├── runner.py                  Run pipeline → artifacts (both tiers)
        ├── judge.py                   LLM-as-judge helper
        ├── report.py                  Aggregate ScoreResult → JSON + markdown
        ├── scorers/
        │   ├── __init__.py
        │   ├── base.py                ScoreResult dataclass
        │   ├── inventory.py
        │   ├── graph.py
        │   ├── stories.py
        │   ├── brd.py
        │   └── design.py
        └── rubrics/
            ├── brd.yaml               Rubric for BRD judge
            └── design.yaml            Rubric for architect judge

tests/
├── eval_corpus/                       [NEW]
│   ├── synthetic/
│   │   ├── corpus.yaml                Corpus metadata (name, repo_path, …)
│   │   ├── expected_inventory.json
│   │   ├── expected_graph.json
│   │   └── expected_stories_shape.json
│   └── aws_legacy/
│       ├── corpus.yaml
│       ├── expected_inventory.json
│       ├── expected_graph.json
│       └── expected_stories_shape.json
├── test_eval_scorers.py
├── test_eval_judge.py
├── test_eval_runner.py
└── test_eval_report.py
```

### 3.3 Reuse of existing infrastructure

- `agent_harness.discovery.workflow.run_discovery` runs the five LLM stages.
  The real-LLM tier calls it directly.
- `agent_harness.discovery.paths` resolves artifact locations.
- Pydantic models from `agent_harness.discovery.artifacts`.
- `agent_harness.base.create_agent` for the judge (a new role added via
  settings.yaml — no code changes in `base`).

## 4. Components

### 4.1 `corpus.py` — corpus loader

```python
@dataclass
class Corpus:
    name: str
    repo_path: Path
    expected_inventory: Inventory
    expected_graph: DependencyGraph
    expected_stories: dict  # see 5.1 — shape, not full text

def load_corpus(name: str) -> Corpus:
    """Load a corpus by name from tests/eval_corpus/<name>/."""
```

`corpus.yaml` is a tiny metadata file: `name: synthetic`, `repo_path:
tests/fixtures/synthetic_repo`. All expected outputs live alongside.

### 4.2 `runner.py` — pipeline invocation

```python
@dataclass
class RunArtifacts:
    inventory: Inventory
    graph: DependencyGraph
    brd: dict[str, str]       # module_id → markdown
    design: dict[str, str]
    stories: Stories
    run_dir: Path             # where artifacts live on disk

async def run_corpus(corpus: Corpus, tier: Literal["deterministic", "real_llm"],
                     repo: MigrationRepository) -> RunArtifacts:
    """Run discovery against the corpus under the chosen tier.

    tier="deterministic": patches each discovery stage's `_run_agent` seam with
        canned responses from tests/fixtures/canned_<corpus>/*.json.
    tier="real_llm": calls the live pipeline. No patches.
    """
```

The deterministic tier loads canned responses from a per-corpus directory —
these are the same JSON strings used in the existing integration tests.

### 4.3 `scorers/` — per-stage scoring

Each scorer imports `ScoreResult` from `scorers/base.py`:

```python
@dataclass
class ScoreResult:
    stage: str                   # scanner|grapher|brd|architect|stories
    score: float                 # 0.0 .. 1.0
    passed: bool
    threshold: float
    details: dict                # scorer-specific (diffs, judge reasoning)
```

Each scorer exposes a single `score(...)` function. Inputs vary by stage but
always include the actual artifact and the expected ground truth:

- `inventory.score(got: Inventory, expected: Inventory) -> ScoreResult`
- `graph.score(got: DependencyGraph, expected: DependencyGraph) -> ScoreResult`
- `stories.score(got: Stories, expected: dict) -> ScoreResult`
- `brd.score(got: dict[str, str], corpus: Corpus, judge: Judge) -> ScoreResult`
- `design.score(got: dict[str, str], corpus: Corpus, judge: Judge) -> ScoreResult`

#### Scoring details

**Inventory (scanner stage):**
- Jaccard on module IDs.
- Passed iff score == 1.0 (no missing / extra modules). Threshold 1.0.
- Details: `{missing: [...], extra: [...]}`.

**Graph (grapher stage):**
- Jaccard on edge triples `(src, dst, kind)`.
- Bonus check: every `aws_resource` node in expected must exist in got.
- Threshold 0.9.
- Details: `{missing_edges: [...], extra_edges: [...], missing_resources: [...]}`.

**Stories:**
- 4 sub-scores, each 0..1, averaged:
  - Epic coverage: every inventory module has an epic in got.
  - Story count per module within ±1 of expected.
  - Dep-edge Jaccard on story dependency graph.
  - Every story has ≥1 acceptance criterion.
- Threshold 0.85.

**BRD:**
- Two components, averaged:
  - Structural (0.5 weight): every module has a BRD; each has non-empty
    `Business Rules`, `Error Paths`, `Side Effects`. Reuses the logic from
    `brd_critic._section_has_content` so the evaluator and the critic stay in
    sync.
  - Judge (0.5 weight): LLM-as-judge against `rubrics/brd.yaml` — rubric
    criteria normalised to 0..1.
- Threshold 0.7.

**Design (architect stage):**
- Same two-component split with `rubrics/design.yaml`.
- Threshold 0.7.

### 4.4 `judge.py` — LLM-as-judge

```python
@dataclass
class Judge:
    model: str = "gpt-5.4-mini"     # overridable via rubric or settings
    temperature: float = 0.0

    async def score(self, rubric: Rubric, artifact: str, context: dict) -> JudgeScore
```

Rubric schema:

```yaml
name: brd
description: Score a module BRD for faithfulness to source + resource coverage.
judge_model: gpt-5.4-mini    # optional override
temperature: 0.0
criteria:
  - name: faithfulness
    weight: 0.4
    description: Every business rule present in the source code is reflected.
  - name: resource_coverage
    weight: 0.3
    description: Every AWS resource referenced in the graph edges for this module appears in the Side Effects section by literal name.
  - name: trigger_coverage
    weight: 0.3
    description: Every trigger in the source has a corresponding bullet in Triggers.
```

Judge prompt:

```
You are a rubric-based evaluator. Score the ARTIFACT against each CRITERION
on a 0–10 scale. Return ONLY JSON:

{
  "criteria": [
    {"name": "faithfulness", "score": <int 0..10>, "reasoning": "..."},
    ...
  ],
  "overall": <weighted mean, 0..10>
}

RUBRIC:
{rubric_yaml}

CONTEXT:
{context_block}

ARTIFACT:
{artifact_text}
```

Returned JSON → `JudgeScore(criteria=[...], overall=<float>)`. Pydantic
validates; on parse failure the scorer marks the stage failed with
`details={"parse_error": ...}`.

### 4.5 `report.py` — aggregation

```python
def render(results: list[ScoreResult], corpus: Corpus, tier: str) -> ReportBundle:
    """Build the report. Writes report.json and report.md to run_dir."""

@dataclass
class ReportBundle:
    corpus: str
    tier: str
    overall_passed: bool
    per_stage: dict[str, ScoreResult]
    run_dir: Path
```

`report.md` layout: one-line verdict (PASS/FAIL), then a per-stage table
(stage | score | threshold | passed), then per-stage detail blocks with
diffs and judge reasoning.

### 4.6 `__main__.py` — CLI

```
python -m agent_harness.eval run
    [--corpus=<name>]       # default: all under tests/eval_corpus/
    [--tier={det,real_llm}] # default: real_llm
    [--out=<dir>]           # default: eval-results/
python -m agent_harness.eval report <run_dir>
```

Exit codes:
- 0 — every scored stage passed its threshold.
- 1 — one or more stages failed.
- 2 — runtime error (pipeline crash, missing corpus, etc.).

## 5. Data contracts

### 5.1 `expected_stories_shape.json`

Story IDs are opaque — the LLM picks them. Comparison is done on the *shape*
of the dependency graph, expressed in **module** terms: "module A has a story
that depends on a story in module B." The scorer projects the run's actual
story dep-edges through the story→module map before comparing.

```json
{
  "expected_epic_modules": ["orders", "payments", "notifications"],
  "expected_story_count_per_module": {"orders": 1, "payments": 1, "notifications": 1},
  "expected_dep_edges": [["payments", "orders"], ["notifications", "payments"]]
}
```

Each edge is `[dependent_module, depends_on_module]`.

### 5.2 `ScoreResult` (returned by every scorer)

Already defined in §4.3. `details` is free-form but must be JSON-serialisable.

### 5.3 `ReportBundle` (returned by runner + CLI)

Already defined in §4.5.

## 6. Control flow

### 6.1 Happy path (real_llm tier)

```
load_corpus(name)
    → runner.run_corpus(corpus, tier=real_llm, repo)
       └─ workflow.run_discovery(repo_id, repo_path, repo)
    → artifacts = RunArtifacts(inventory, graph, brd, design, stories, run_dir)
    → results = [
         inventory.score(...), graph.score(...), stories.score(...),
         brd.score(...),       design.score(...),
      ]
    → report.render(results, corpus, tier)
    → exit(0 if all passed else 1)
```

### 6.2 Deterministic tier

The runner patches `_run_agent` on every discovery module with canned
responses loaded from `tests/eval_corpus/<name>/canned/` (copies of the
responses already used in `tests/test_discovery_e2e.py`). Same scoring path.

### 6.3 Corpus authoring workflow

When adding a new corpus:
1. Place the repo (or symlink) under `tests/eval_corpus/<name>/repo` (or set
   `repo_path` in `corpus.yaml`).
2. Hand-author `expected_inventory.json` (list of modules + handler paths).
3. Run the real-LLM tier once to capture a baseline graph + stories; review
   by hand and copy to `expected_graph.json` / `expected_stories_shape.json`
   once satisfied.
4. For the canned/deterministic tier: capture the real-LLM's raw stage
   outputs into `canned/` directory (one JSON per stage).

No tooling for step 3/4 in v1 — manual authoring. Sub-project C.2 can add a
`freeze-baseline` CLI subcommand.

## 7. Error handling

| Condition | Behaviour |
|---|---|
| Corpus missing | `FileNotFoundError` → exit 2 |
| Expected artifact missing | `ScoreResult(passed=False, details={expected_missing})` — other stages continue |
| Pipeline crashes inside a stage | Catch, set that stage's result to `passed=False`, skip dependent stages (grapher without inventory cannot run) |
| Judge LLM parse failure | That stage `ScoreResult(passed=False, score=0.0, details={parse_error: ...})` |
| Judge LLM rate-limit | Existing `run_with_retry` handles; if all retries fail → same as parse failure |
| Threshold unchanged but real-LLM got 0.91 → 0.905 | PASS — threshold is absolute, not delta |
| Corpus repo path unreadable | `FileNotFoundError` → exit 2 |

## 8. Testing

Unit (no LLM):
- `scorers/inventory`: exact match, missing, extra, mixed.
- `scorers/graph`: Jaccard edge cases (empty, identical, disjoint, partial).
- `scorers/stories`: all 4 sub-scores independently.
- `scorers/brd`: structural component passes/fails; judge mocked.
- `scorers/design`: structural component passes/fails; judge mocked.
- `judge.score`: mocked LLM returning valid JSON, malformed JSON, empty.
- `runner.run_corpus(tier=deterministic)`: end-to-end with mocked `_run_agent`
  using canned responses; asserts RunArtifacts shape.
- `report.render`: markdown contains per-stage rows; JSON round-trips.

Integration (mocked LLM):
- Full pipeline `runner.run_corpus(tier=deterministic)` over the synthetic
  corpus; every scorer returns `passed=True`.

Real-LLM: not in unit suite. Manual validation via
`python -m agent_harness.eval run --tier=real_llm --corpus=synthetic`.

## 9. Migration plan (how this ships)

1. `ScoreResult` + `scorers/base.py`.
2. Inventory + graph + stories scorers (structured, easiest).
3. Judge helper + rubric YAMLs.
4. BRD + design scorers (free-form; depend on judge).
5. Corpus loader + synthetic fixture (expected files hand-authored).
6. Runner (both tiers).
7. Report aggregation.
8. CLI.
9. Second corpus: `aws_legacy`. Requires running real LLM once to seed
   expected files, then human review.
10. README section on how to run.

Each step is independently testable.

## 10. Open questions (none blocking)

- Judge model: same `gpt-5.4-mini` as the pipeline for v1 (cost simplicity).
  Rubric YAML allows per-rubric override if bias becomes a problem.
- Thresholds may need tuning after the first few real runs. `config/eval.yaml`
  could externalise them later; v1 hard-codes them in each scorer.
- When the real-LLM tier flakes on a specific stage, we currently retry via
  `run_with_retry`. If flakes persist, a `--retries=N` CLI flag can gate a
  re-score attempt; not in v1.

---

**Next step:** user reviews, then implementation plan via `writing-plans`.
