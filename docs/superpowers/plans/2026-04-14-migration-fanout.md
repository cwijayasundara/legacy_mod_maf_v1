# Migration Fanout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the approved discovery backlog to the existing `/migrate` pipeline, wave by wave, and relax the `src/lambda/<module>/` path constraint so arbitrary repo layouts (handler file + shared-services package) can be migrated.

**Architecture:** Extend `BacklogItem` and `MigrationRequest` with optional `source_paths` + `context_paths`. `WaveScheduler` populates those from the inventory + graph. `MigrationPipeline.run` passes them through to `analyzer`/`coder`/`tester`. A new `agent_harness/fanout.py` orchestrates wave-by-wave, concurrent-within-wave, continue-on-error execution; descendants of failed modules in the story DAG are `skipped`. Three new FastAPI endpoints expose it.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, SQLite (via existing `MigrationRepository`), `pytest` + `pytest-asyncio`. All paths in this plan are relative to `ms-agent-harness/` unless stated otherwise. Pre-existing failures in `tests/test_chunker.py`, `tests/test_complexity_scorer.py`, `tests/test_compressor.py`, `tests/test_token_estimator.py`, `tests/test_integration.py`, `tests/test_ast_tools.py` are unrelated to this work — only scope regression checks to the files this plan touches. Run tests with `python3 -m pytest`.

---

## File Structure

| File | Responsibility |
|---|---|
| `agent_harness/discovery/artifacts.py` | +2 optional fields on `BacklogItem` |
| `agent_harness/discovery/wave_scheduler.py` | `schedule()` now takes `inventory`+`graph`, populates paths |
| `agent_harness/discovery/workflow.py` | `run_planning()` loads `graph.json` and passes it to `schedule` |
| `agent_harness/persistence/repository.py` | Two new tables + 4 new methods |
| `agent_harness/analyzer.py` | `analyze_module` gains optional `source_paths`, `context_paths` kwargs |
| `agent_harness/coder.py` | `migrate_module` gains the same two kwargs |
| `agent_harness/tester.py` | `evaluate_module` gains the same two kwargs |
| `agent_harness/pipeline.py` | `MigrationPipeline.run` plumbs kwargs through |
| `agent_harness/orchestrator/api.py` | `MigrationRequest` +2 fields, relaxed `_validate`; 3 new endpoints |
| `agent_harness/fanout.py` | **NEW** — `migrate_repo` orchestration |
| `tests/test_backlog_item_paths.py` | **NEW** — round-trip of new fields |
| `tests/test_wave_scheduler_paths.py` | **NEW** — path derivation logic |
| `tests/test_migrate_repo_repository.py` | **NEW** — CRUD for the two new tables |
| `tests/test_migrate_request_paths.py` | **NEW** — request validation |
| `tests/test_pipeline_paths.py` | **NEW** — `pipeline.run` forwards kwargs |
| `tests/test_fanout.py` | **NEW** — waves, concurrency, skip propagation, approval gate |
| `tests/test_migrate_repo_api.py` | **NEW** — endpoint behaviour |
| `tests/test_fanout_e2e.py` | **NEW** — discover → plan → approve → migrate-repo end-to-end (mocked LLM) |
| `README.md` | Append fanout workflow section |

**Conventions:**
- Tests patch the real LLM by injecting `AsyncMock` into the single `_run_agent` / `MigrationPipeline.run` seam (same pattern used throughout the discovery tests).
- Commit messages use Conventional Commits.
- Each task is a separate commit.

---

## Task 1: Extend `BacklogItem` with optional path fields

**Files:**
- Modify: `agent_harness/discovery/artifacts.py`
- Test: `tests/test_backlog_item_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backlog_item_paths.py
import json
from agent_harness.discovery.artifacts import BacklogItem


def test_backlog_item_defaults_empty_lists():
    item = BacklogItem(module="orders", language="python", wave=1)
    assert item.source_paths == []
    assert item.context_paths == []


def test_backlog_item_round_trips_with_paths():
    item = BacklogItem(
        module="orders", language="python", wave=1,
        source_paths=["/abs/a.py"],
        context_paths=["/abs/services/b.py", "/abs/services/c.py"],
    )
    again = BacklogItem.model_validate_json(item.model_dump_json())
    assert again == item


def test_legacy_backlog_item_still_loads():
    """BacklogItem written before Task 1 (no new fields) must still validate."""
    legacy = {"module": "orders", "language": "python", "wave": 1,
              "work_item_id": "S1", "title": "", "description": "",
              "acceptance_criteria": ""}
    item = BacklogItem.model_validate(legacy)
    assert item.source_paths == []
    assert item.context_paths == []


def test_migrate_request_still_superset():
    """BacklogItem minus wave/source_paths/context_paths must still validate as MigrationRequest."""
    from agent_harness.orchestrator.api import MigrationRequest
    item = BacklogItem(module="orders", language="python", wave=1,
                       source_paths=["/a"], context_paths=["/b"])
    payload = json.loads(item.model_dump_json())
    for k in ("wave", "source_paths", "context_paths"):
        payload.pop(k)
    MigrationRequest.model_validate(payload)  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_backlog_item_paths.py -v`
Expected: FAIL on `source_paths == []` (field does not exist).

- [ ] **Step 3: Add the two fields**

Edit `agent_harness/discovery/artifacts.py`. Locate `class BacklogItem(BaseModel):` and add the two fields *before* `wave`:

```python
class BacklogItem(BaseModel):
    """Strict superset of MigrationRequest in orchestrator/api.py.

    Drop the wave/source_paths/context_paths fields and the rest must
    validate as MigrationRequest.
    """
    module: str
    language: str
    work_item_id: str = "LOCAL"
    title: str = ""
    description: str = ""
    acceptance_criteria: str = ""
    source_paths: list[str] = Field(default_factory=list)
    context_paths: list[str] = Field(default_factory=list)
    wave: int
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_backlog_item_paths.py tests/test_discovery_artifacts.py -v`
Expected: 4 new + 5 existing = 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/discovery/artifacts.py tests/test_backlog_item_paths.py
git commit -m "feat(discovery): add optional source_paths and context_paths to BacklogItem"
```

---

## Task 2: New SQLite tables — `migrate_repo_runs` + `migrate_repo_module_runs`

**Files:**
- Modify: `agent_harness/persistence/repository.py`
- Test: `tests/test_migrate_repo_repository.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrate_repo_repository.py
import pytest
from agent_harness.persistence.repository import MigrationRepository


@pytest.fixture
def repo(tmp_path):
    r = MigrationRepository(db_path=tmp_path / "test.db")
    r.initialize()
    return r


def test_create_migrate_repo_run_returns_id(repo):
    run_id = repo.create_migrate_repo_run("my-repo")
    assert isinstance(run_id, int) and run_id > 0


def test_record_module_and_get(repo):
    run_id = repo.create_migrate_repo_run("my-repo")
    repo.record_migrate_module(run_id, "orders", wave=1,
                                status="completed", review_score=87)
    repo.record_migrate_module(run_id, "payments", wave=2,
                                status="skipped", reason="orders failed")
    run = repo.get_migrate_repo_run("my-repo")
    assert run["status"] == "running"
    modules = {m["module"]: m for m in run["modules"]}
    assert modules["orders"]["status"] == "completed"
    assert modules["orders"]["review_score"] == 87
    assert modules["payments"]["status"] == "skipped"
    assert modules["payments"]["reason"] == "orders failed"


def test_complete_migrate_repo_run(repo):
    run_id = repo.create_migrate_repo_run("my-repo")
    repo.complete_migrate_repo_run(run_id, "partial")
    run = repo.get_migrate_repo_run("my-repo")
    assert run["status"] == "partial"
    assert run["completed_at"] is not None


def test_get_returns_latest_run(repo):
    r1 = repo.create_migrate_repo_run("my-repo")
    repo.complete_migrate_repo_run(r1, "failed")
    r2 = repo.create_migrate_repo_run("my-repo")
    run = repo.get_migrate_repo_run("my-repo")
    assert run["id"] == r2
    assert run["status"] == "running"


def test_get_returns_none_for_unknown_repo(repo):
    assert repo.get_migrate_repo_run("ghost") is None


def test_update_module_status(repo):
    """record_migrate_module should upsert on (run_id, module)."""
    run_id = repo.create_migrate_repo_run("my-repo")
    repo.record_migrate_module(run_id, "orders", wave=1, status="running")
    repo.record_migrate_module(run_id, "orders", wave=1,
                                status="completed", review_score=90)
    run = repo.get_migrate_repo_run("my-repo")
    assert len(run["modules"]) == 1
    assert run["modules"][0]["status"] == "completed"
    assert run["modules"][0]["review_score"] == 90
```

- [ ] **Step 2: Run tests**

Run: `python3 -m pytest tests/test_migrate_repo_repository.py -v`
Expected: AttributeError — `create_migrate_repo_run` not defined.

- [ ] **Step 3: Extend the schema**

In `agent_harness/persistence/repository.py`, append to the `executescript` block inside `initialize`:

```python
                CREATE TABLE IF NOT EXISTS migrate_repo_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running'
                );

                CREATE TABLE IF NOT EXISTS migrate_repo_module_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_run_id INTEGER NOT NULL,
                    module TEXT NOT NULL,
                    wave INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT DEFAULT '',
                    review_score INTEGER,
                    completed_at TEXT,
                    UNIQUE(repo_run_id, module)
                );

                CREATE INDEX IF NOT EXISTS idx_mrr_repo ON migrate_repo_runs(repo_id);
                CREATE INDEX IF NOT EXISTS idx_mrmr_run ON migrate_repo_module_runs(repo_run_id);
```

- [ ] **Step 4: Add the four methods**

Append the following methods to `MigrationRepository` before the module-level `_now`:

```python
    # ─── Migrate Repo Runs ─────────────────────────────────────────────

    def create_migrate_repo_run(self, repo_id: str) -> int:
        self.initialize()
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO migrate_repo_runs (repo_id, started_at, status)
                   VALUES (?, ?, 'running')""",
                (repo_id, _now()),
            )
            return cursor.lastrowid

    def record_migrate_module(self, run_id: int, module: str, wave: int,
                              status: str, reason: str = "",
                              review_score: int | None = None) -> None:
        self.initialize()
        with self._connect() as conn:
            completed = _now() if status in {"completed", "failed", "skipped"} else None
            conn.execute(
                """INSERT INTO migrate_repo_module_runs
                       (repo_run_id, module, wave, status, reason, review_score, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(repo_run_id, module) DO UPDATE SET
                       wave = excluded.wave,
                       status = excluded.status,
                       reason = excluded.reason,
                       review_score = excluded.review_score,
                       completed_at = excluded.completed_at""",
                (run_id, module, wave, status, reason, review_score, completed),
            )

    def complete_migrate_repo_run(self, run_id: int, status: str) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "UPDATE migrate_repo_runs SET status = ?, completed_at = ? WHERE id = ?",
                (status, _now(), run_id),
            )

    def get_migrate_repo_run(self, repo_id: str) -> dict | None:
        self.initialize()
        with self._connect() as conn:
            run = conn.execute(
                """SELECT * FROM migrate_repo_runs WHERE repo_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (repo_id,),
            ).fetchone()
            if not run:
                return None
            rows = conn.execute(
                """SELECT module, wave, status, reason, review_score, completed_at
                   FROM migrate_repo_module_runs WHERE repo_run_id = ?
                   ORDER BY wave, module""",
                (run["id"],),
            ).fetchall()
            data = dict(run)
            data["modules"] = [dict(r) for r in rows]
            return data
```

- [ ] **Step 5: Run tests (new + regression)**

Run: `python3 -m pytest tests/test_migrate_repo_repository.py tests/test_discovery_repository.py tests/test_repository.py -v`
Expected: 6 new + existing discovery + existing migration tests all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_harness/persistence/repository.py tests/test_migrate_repo_repository.py
git commit -m "feat(persistence): add migrate_repo_runs + migrate_repo_module_runs tables"
```

---

## Task 3: Extend `WaveScheduler.schedule` to populate paths + update caller

**Files:**
- Modify: `agent_harness/discovery/wave_scheduler.py`
- Modify: `agent_harness/discovery/workflow.py` (`run_planning`)
- Test: `tests/test_wave_scheduler_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wave_scheduler_paths.py
from pathlib import Path

from agent_harness.discovery.artifacts import (
    Stories, Story, Epic, AcceptanceCriterion, Inventory, ModuleRecord,
    DependencyGraph, GraphNode, GraphEdge,
)
from agent_harness.discovery.wave_scheduler import schedule


def _story(sid, mod="orders", deps=()):
    return Story(id=sid, epic_id="E-" + mod, title="t", description="d",
                 acceptance_criteria=[AcceptanceCriterion(text="ac")],
                 depends_on=list(deps), blocks=[], estimate="M")


def _stories(stories_by_mod: dict[str, list[Story]]) -> Stories:
    epics = [Epic(id=f"E-{m}", module_id=m, title="E",
                  story_ids=[s.id for s in sl])
             for m, sl in stories_by_mod.items()]
    flat = [s for sl in stories_by_mod.values() for s in sl]
    return Stories(epics=epics, stories=flat)


def test_source_paths_use_handler_entrypoint(tmp_path):
    (tmp_path / "orders").mkdir()
    (tmp_path / "orders" / "handler.py").write_text("def handler(e,c): pass\n")

    inv = Inventory(
        repo_meta={"root_path": str(tmp_path), "total_files": 1,
                   "total_loc": 1, "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path="orders", language="python",
                              handler_entrypoint="orders/handler.py",
                              loc=1, config_files=[])],
    )
    graph = DependencyGraph(nodes=[], edges=[])
    stories = _stories({"orders": [_story("S1", "orders")]})
    backlog = schedule(stories, language_by_module={"orders": "python"},
                       inventory=inv, graph=graph)
    assert len(backlog.items) == 1
    item = backlog.items[0]
    assert item.source_paths == [str(tmp_path / "orders" / "handler.py")]
    assert item.context_paths == []


def test_context_paths_include_shared_siblings(tmp_path):
    """Handler imports ..services → all *.py under services/ land in context_paths."""
    (tmp_path / "handlers").mkdir()
    (tmp_path / "handlers" / "orders.py").write_text("from ..services import x\n")
    (tmp_path / "services").mkdir()
    (tmp_path / "services" / "x.py").write_text("def x(): pass\n")
    (tmp_path / "services" / "y.py").write_text("def y(): pass\n")

    inv = Inventory(
        repo_meta={"root_path": str(tmp_path), "total_files": 3,
                   "total_loc": 3, "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path="handlers", language="python",
                              handler_entrypoint="handlers/orders.py",
                              loc=1, config_files=[])],
    )
    graph = DependencyGraph(
        nodes=[GraphNode(id="orders", kind="module", attrs={"path": "handlers"})],
        edges=[GraphEdge(src="orders", dst="services", kind="imports")],
    )
    stories = _stories({"orders": [_story("S1", "orders")]})
    backlog = schedule(stories, language_by_module={"orders": "python"},
                       inventory=inv, graph=graph)
    ctx = set(backlog.items[0].context_paths)
    assert str(tmp_path / "services" / "x.py") in ctx
    assert str(tmp_path / "services" / "y.py") in ctx


def test_context_skips_backlog_peer_module(tmp_path):
    """Imports between two modules both being migrated → NOT in context."""
    (tmp_path / "orders").mkdir()
    (tmp_path / "orders" / "handler.py").write_text("from payments import x\n")
    (tmp_path / "payments").mkdir()
    (tmp_path / "payments" / "handler.py").write_text("def x(): pass\n")

    inv = Inventory(
        repo_meta={"root_path": str(tmp_path), "total_files": 2,
                   "total_loc": 2, "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py", loc=1, config_files=[]),
            ModuleRecord(id="payments", path="payments", language="python",
                         handler_entrypoint="payments/handler.py", loc=1, config_files=[]),
        ],
    )
    graph = DependencyGraph(
        nodes=[GraphNode(id="orders", kind="module", attrs={"path": "orders"}),
               GraphNode(id="payments", kind="module", attrs={"path": "payments"})],
        edges=[GraphEdge(src="orders", dst="payments", kind="imports")],
    )
    stories = _stories({
        "orders": [_story("S1", "orders", deps=["S2"])],
        "payments": [_story("S2", "payments")],
    })
    backlog = schedule(stories, language_by_module={"orders": "python", "payments": "python"},
                       inventory=inv, graph=graph)
    orders_item = next(i for i in backlog.items if i.module == "orders")
    assert orders_item.context_paths == []


def test_source_paths_default_when_no_inventory_match():
    """Edge case: a story whose module is not in the inventory (shouldn't happen,
    but we don't want to crash)."""
    from agent_harness.discovery.artifacts import Inventory, DependencyGraph
    inv = Inventory(
        repo_meta={"root_path": "/nope", "total_files": 0, "total_loc": 0,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[],
    )
    graph = DependencyGraph(nodes=[], edges=[])
    stories = _stories({"ghost": [_story("S1", "ghost")]})
    backlog = schedule(stories, language_by_module={"ghost": "python"},
                       inventory=inv, graph=graph)
    assert backlog.items[0].source_paths == []
    assert backlog.items[0].context_paths == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_wave_scheduler_paths.py -v`
Expected: TypeError — `schedule` got unexpected keyword argument `inventory`.

- [ ] **Step 3: Extend `wave_scheduler.py`**

Replace the body of `schedule` in `agent_harness/discovery/wave_scheduler.py` with:

```python
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from .artifacts import Backlog, BacklogItem, DependencyGraph, Inventory, Stories


class CycleError(ValueError):
    pass


def schedule(stories: Stories, language_by_module: dict[str, str],
             inventory: Inventory | None = None,
             graph: DependencyGraph | None = None) -> Backlog:
    by_id = {s.id: s for s in stories.stories}

    for s in stories.stories:
        for dep in s.depends_on:
            if dep not in by_id:
                raise ValueError(f"Story {s.id} depends_on unknown story id: {dep}")

    indeg: dict[str, int] = {sid: 0 for sid in by_id}
    succ: dict[str, list[str]] = defaultdict(list)
    for s in stories.stories:
        for dep in s.depends_on:
            indeg[s.id] += 1
            succ[dep].append(s.id)

    epic_module: dict[str, str] = {e.id: e.module_id for e in stories.epics}

    layer_of: dict[str, int] = {}
    queue = deque(sorted(sid for sid, d in indeg.items() if d == 0))
    while queue:
        sid = queue.popleft()
        my_layer = max((layer_of[d] for d in by_id[sid].depends_on), default=0) + 1
        layer_of[sid] = my_layer
        for n in succ[sid]:
            indeg[n] -= 1
            if indeg[n] == 0:
                queue.append(n)

    if len(layer_of) != len(by_id):
        unresolved = sorted(set(by_id) - set(layer_of))
        raise CycleError(f"Cycle detected involving stories: {unresolved}")

    # Pre-compute per-module path info.
    backlog_modules = {epic_module.get(s.epic_id, s.epic_id) for s in stories.stories}
    src_by_mod, ctx_by_mod = _compute_paths(inventory, graph, backlog_modules)

    items: list[BacklogItem] = []
    for sid in sorted(by_id, key=lambda x: (layer_of[x], x)):
        s = by_id[sid]
        module = epic_module.get(s.epic_id, s.epic_id)
        ac = "\n".join(c.text for c in s.acceptance_criteria)
        items.append(BacklogItem(
            module=module,
            language=language_by_module.get(module, "python"),
            work_item_id=s.id,
            title=s.title,
            description=s.description,
            acceptance_criteria=ac,
            source_paths=src_by_mod.get(module, []),
            context_paths=ctx_by_mod.get(module, []),
            wave=layer_of[sid],
        ))
    return Backlog(items=items)


def _compute_paths(inventory: Inventory | None, graph: DependencyGraph | None,
                   backlog_modules: set[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    src: dict[str, list[str]] = {}
    ctx: dict[str, list[str]] = {}
    if inventory is None:
        return src, ctx

    root = Path(inventory.repo_meta.root_path).resolve()
    inv_by_id = {m.id: m for m in inventory.modules}

    for m in inventory.modules:
        if m.id not in backlog_modules:
            continue
        src[m.id] = [str((root / m.handler_entrypoint).resolve())]
        ctx[m.id] = []

    if graph is None:
        return src, ctx

    for edge in graph.edges:
        if edge.kind != "imports":
            continue
        if edge.src not in backlog_modules:
            continue
        if edge.dst in backlog_modules:
            continue  # peer module, handled separately
        # Resolve the dst path. If dst is an inventory module, use its path;
        # otherwise treat dst as a directory name under root.
        dst_dir = (root / inv_by_id[edge.dst].path).resolve() \
            if edge.dst in inv_by_id else (root / edge.dst).resolve()
        if not dst_dir.is_dir():
            continue
        for py in sorted(dst_dir.rglob("*.py")):
            ctx[edge.src].append(str(py.resolve()))

    # Dedupe preserving order.
    for k, vs in ctx.items():
        seen: set[str] = set()
        ctx[k] = [v for v in vs if not (v in seen or seen.add(v))]

    return src, ctx
```

- [ ] **Step 4: Update existing wave_scheduler callers**

`agent_harness/discovery/workflow.py` — change `run_planning`:

```python
async def run_planning(repo_id: str, repo: MigrationRepository) -> Backlog:
    """Run the deterministic WaveScheduler over stored artifacts."""
    from .wave_scheduler import schedule

    inv_path = paths.inventory_path(repo_id)
    graph_path = paths.graph_path(repo_id)
    stories_path = paths.stories_path(repo_id)
    for p in (inv_path, graph_path, stories_path):
        if not p.exists():
            raise FileNotFoundError(f"missing artifact: {p}")

    inventory = Inventory.model_validate_json(inv_path.read_text())
    graph = DependencyGraph.model_validate_json(graph_path.read_text())
    stories = Stories.model_validate_json(stories_path.read_text())
    lang_by_module = {m.id: m.language for m in inventory.modules}
    backlog = schedule(stories, language_by_module=lang_by_module,
                       inventory=inventory, graph=graph)

    out = paths.backlog_path(repo_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(backlog.model_dump_json(indent=2), encoding="utf-8")
    return backlog
```

- [ ] **Step 5: Update existing wave_scheduler tests**

In `tests/test_wave_scheduler.py`, every call `schedule(s, language_by_module=...)` keeps working because `inventory` and `graph` are optional (default `None`). Do NOT modify this file. Confirm via test run.

- [ ] **Step 6: Run all affected tests**

Run: `python3 -m pytest tests/test_wave_scheduler.py tests/test_wave_scheduler_paths.py tests/test_discovery_workflow.py tests/test_discovery_e2e.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add agent_harness/discovery/wave_scheduler.py \
        agent_harness/discovery/workflow.py \
        tests/test_wave_scheduler_paths.py
git commit -m "feat(discovery): wave scheduler populates source_paths and context_paths"
```

---

## Task 4: Relax `MigrationRequest` validation

**Files:**
- Modify: `agent_harness/orchestrator/api.py`
- Test: `tests/test_migrate_request_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrate_request_paths.py
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from agent_harness.orchestrator import api as api_mod
    api_mod._pipeline = None
    api_mod._ado = None
    return TestClient(api_mod.app)


def test_legacy_request_still_404s_when_src_lambda_missing(client, tmp_path):
    """The legacy PROJECT_ROOT/src/lambda/<module>/ path still governs when
    source_paths is empty."""
    resp = client.post("/migrate", json={
        "module": "no-such", "language": "python",
    })
    assert resp.status_code == 404


def test_request_with_source_paths_skips_legacy_check(client, tmp_path):
    handler = tmp_path / "orders_handler.py"
    handler.write_text("def handler(e,c): pass\n")
    resp = client.post("/migrate", json={
        "module": "orders", "language": "python",
        "source_paths": [str(handler)],
    })
    # Accepted (background task queued) — not 404.
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


def test_request_with_missing_source_path_404s(client, tmp_path):
    resp = client.post("/migrate", json={
        "module": "orders", "language": "python",
        "source_paths": [str(tmp_path / "ghost.py")],
    })
    assert resp.status_code == 404


def test_request_with_missing_context_path_404s(client, tmp_path):
    handler = tmp_path / "h.py"
    handler.write_text("pass\n")
    resp = client.post("/migrate", json={
        "module": "orders", "language": "python",
        "source_paths": [str(handler)],
        "context_paths": [str(tmp_path / "ghost.py")],
    })
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify partial fail**

Run: `python3 -m pytest tests/test_migrate_request_paths.py -v`
Expected: new path-carrying tests fail with 404 (current `_validate` ignores `source_paths`).

- [ ] **Step 3: Extend the request and validator**

In `agent_harness/orchestrator/api.py`, update `MigrationRequest`:

```python
class MigrationRequest(BaseModel):
    module: str = Field(..., description="Lambda module name (directory under src/lambda/)")
    language: str = Field(..., description="Source language: python, node, java, csharp")
    work_item_id: str = Field(default="LOCAL")
    title: str = Field(default="")
    description: str = Field(default="")
    acceptance_criteria: str = Field(default="")
    source_paths: list[str] = Field(default_factory=list,
        description="Optional explicit source paths. When provided, bypasses src/lambda/<module>/ lookup.")
    context_paths: list[str] = Field(default_factory=list,
        description="Optional read-only context paths shown to the migrator.")
```

Replace `_validate`:

```python
def _validate(req: MigrationRequest):
    if req.language not in {"python", "node", "java", "csharp"}:
        raise HTTPException(400, f"Invalid language: {req.language}")
    if req.source_paths:
        for p in req.source_paths:
            if not os.path.exists(p):
                raise HTTPException(404, f"source path not found: {p}")
        for p in req.context_paths:
            if not os.path.exists(p):
                raise HTTPException(404, f"context path not found: {p}")
        return
    # Legacy behaviour.
    source = os.path.join(PROJECT_ROOT, "src", "lambda", req.module)
    if not os.path.isdir(source):
        raise HTTPException(404, f"Lambda source not found at src/lambda/{req.module}/")
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_migrate_request_paths.py tests/test_discovery_api.py -v`
Expected: 4 new + 5 existing = 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/orchestrator/api.py tests/test_migrate_request_paths.py
git commit -m "feat(orchestrator): accept explicit source_paths/context_paths on /migrate"
```

---

## Task 5: Extend `analyzer`/`coder`/`tester` with optional paths

**Files:**
- Modify: `agent_harness/analyzer.py`
- Modify: `agent_harness/coder.py`
- Modify: `agent_harness/tester.py`
- Test: none new; regression covered by Task 6 + E2E.

The existing unit tests for analyzer/coder/tester are narrow; full coverage of the new kwargs lives in the pipeline + fanout E2E tests. This task adds the signature extensions with deterministic path-injection behaviour so Task 6 can wire them up without surprises.

- [ ] **Step 1: Modify `analyzer.analyze_module`**

Open `agent_harness/analyzer.py`. Replace the `analyze_module` signature and body below line 40:

```python
async def analyze_module(
    module: str, language: str, source_dir: str,
    source_paths: list[str] | tuple = (),
    context_paths: list[str] | tuple = (),
) -> str:
    """Analyze a Lambda module for migration to Azure Functions.

    When source_paths is provided, those files (not a rglob of source_dir)
    are the sole source. context_paths are listed read-only.
    """
    agent = create_analyzer()

    output_dir = Path("migration-analysis") / module
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis_path = output_dir / "analysis.md"

    file_contents: list[str] = []
    if source_paths:
        for spath in source_paths:
            p = Path(spath)
            if not p.is_file():
                continue
            if needs_chunking(p):
                for i, chunk in enumerate(chunk_file(p)):
                    file_contents.append(f"--- {p} (chunk {i + 1}) ---\n{chunk}")
            else:
                file_contents.append(
                    f"--- {p} ---\n{p.read_text(encoding='utf-8', errors='replace')}"
                )
    else:
        src = Path(source_dir)
        for fpath in sorted(src.rglob("*")):
            if fpath.is_file() and not fpath.name.startswith("."):
                if needs_chunking(fpath):
                    for i, chunk in enumerate(chunk_file(fpath)):
                        file_contents.append(f"--- {fpath} (chunk {i + 1}) ---\n{chunk}")
                else:
                    file_contents.append(
                        f"--- {fpath} ---\n{fpath.read_text(encoding='utf-8', errors='replace')}"
                    )

    if context_paths:
        file_contents.append(
            "\n## CONTEXT (read-only — do NOT migrate these files; "
            "treat as an anti-corruption boundary)\n"
        )
        for cpath in context_paths:
            p = Path(cpath)
            if p.is_file():
                file_contents.append(
                    f"--- {p} (read-only) ---\n{p.read_text(encoding='utf-8', errors='replace')}"
                )

    source_listing = "\n\n".join(file_contents)
    complexity = await score_complexity(source_dir, language)

    prompt = (
        f"Analyze the AWS Lambda module '{module}' ({language}) for migration "
        f"to Azure Functions.\n\n"
        f"## Pre-computed Complexity Score\n"
        f"- Overall complexity: {complexity['overall']}\n"
        f"- AWS dependency count: {complexity['aws_dependency_count']}\n"
        f"- Inter-service coupling: {complexity['coupling_score']}\n"
        f"- Trigger count: {complexity['trigger_count']}\n\n"
        f"## Source Files\n\n{source_listing}\n\n"
        f"Write your full analysis to: {analysis_path}\n"
        f"Follow the output format from your system instructions exactly."
    )

    result = await run_with_retry(agent, prompt, max_retries=3)
    analysis_path.write_text(result, encoding="utf-8")
    return str(analysis_path)
```

- [ ] **Step 2: Modify `coder.migrate_module`**

Open `agent_harness/coder.py`. Replace the `migrate_module` signature and only the sections that format the source listing. Locate line 98; change to:

```python
async def migrate_module(
    module: str, language: str, source_dir: str, analysis_path: str,
    attempt: int = 1,
    source_paths: list[str] | tuple = (),
    context_paths: list[str] | tuple = (),
) -> str:
```

Inside the function, locate the block that reads source files (it does a `Path(source_dir).rglob`). Replace it with:

```python
    # Gather source files to migrate.
    src_blocks: list[str] = []
    targets = [Path(p) for p in source_paths] if source_paths else [
        p for p in Path(source_dir).rglob("*") if p.is_file() and not p.name.startswith(".")
    ]
    for p in targets:
        if not p.is_file():
            continue
        if needs_chunking(p):
            for i, chunk in enumerate(chunk_file(p)):
                src_blocks.append(f"--- {p} (chunk {i + 1}) ---\n{chunk}")
        else:
            src_blocks.append(
                f"--- {p} ---\n{p.read_text(encoding='utf-8', errors='replace')}"
            )

    if context_paths:
        src_blocks.append(
            "\n## CONTEXT (read-only — anti-corruption boundary)\n"
            "You MAY import from these files, but MUST NOT modify or re-create them.\n"
        )
        for cpath in context_paths:
            p = Path(cpath)
            if p.is_file():
                src_blocks.append(
                    f"--- {p} (read-only) ---\n{p.read_text(encoding='utf-8', errors='replace')}"
                )

    source_listing = "\n\n".join(src_blocks)
```

Leave the rest of `migrate_module` untouched — any existing reference to `source_listing` downstream still works.

- [ ] **Step 3: Modify `tester.evaluate_module`**

Open `agent_harness/tester.py`. Replace the signature at line 72:

```python
async def evaluate_module(
    module: str, language: str, contract: str, attempt: int = 1,
    source_paths: list[str] | tuple = (),
    context_paths: list[str] | tuple = (),
) -> str:
```

Within the function, locate the hardcoded `Source Lambda: src/lambda/{module}/` reference in the prompt and replace that block with:

```python
    if source_paths:
        src_listing = "Source files: " + ", ".join(source_paths)
    else:
        src_listing = f"Source Lambda: src/lambda/{module}/"
    if context_paths:
        src_listing += "\nRead-only context: " + ", ".join(context_paths)
```

Then use `src_listing` inside the prompt in place of the old line.

- [ ] **Step 4: Sanity-check imports**

Run: `python3 -c "from agent_harness.analyzer import analyze_module; from agent_harness.coder import migrate_module; from agent_harness.tester import evaluate_module; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/analyzer.py agent_harness/coder.py agent_harness/tester.py
git commit -m "feat(pipeline): analyzer/coder/tester accept source_paths and context_paths"
```

---

## Task 6: Plumb paths through `MigrationPipeline.run`

**Files:**
- Modify: `agent_harness/pipeline.py`
- Test: `tests/test_pipeline_paths.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_paths.py
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.pipeline import MigrationPipeline


@pytest.mark.asyncio
async def test_pipeline_forwards_paths_to_analyzer_and_coder(tmp_path, monkeypatch):
    """When source_paths is supplied, analyzer/coder/tester receive the same paths."""
    monkeypatch.chdir(tmp_path)
    pipe = MigrationPipeline(project_root=str(tmp_path))
    await pipe.initialize()

    handler = tmp_path / "handler.py"
    handler.write_text("def handler(e,c): pass\n")

    with patch("agent_harness.pipeline.analyze_module",
               new=AsyncMock(return_value="analysis text")) as azm, \
         patch("agent_harness.pipeline.propose_contract",
               new=AsyncMock(return_value="contract")) as pc, \
         patch("agent_harness.pipeline.finalize_contract",
               new=AsyncMock(return_value="contract")), \
         patch("agent_harness.pipeline.migrate_module",
               new=AsyncMock(return_value="migrated")) as mm, \
         patch("agent_harness.pipeline.evaluate_module",
               new=AsyncMock(return_value="PASS")) as em, \
         patch("agent_harness.pipeline.review_module",
               new=AsyncMock(return_value={"recommendation": "APPROVE",
                                            "confidence_score": 90,
                                            "coverage": 85})) as rm, \
         patch("agent_harness.pipeline.security_review",
               new=AsyncMock(return_value={"recommendation": "APPROVE"})):
        result = await pipe.run(
            module="orders", language="python",
            source_paths=[str(handler)],
            context_paths=[],
        )

    assert result.status in {"completed", "changes_requested"}
    # analyzer/coder/tester must have received the paths.
    _, kwargs = azm.call_args
    assert kwargs.get("source_paths") == [str(handler)]
    _, kwargs = mm.call_args
    assert kwargs.get("source_paths") == [str(handler)]
    _, kwargs = em.call_args
    assert kwargs.get("source_paths") == [str(handler)]


@pytest.mark.asyncio
async def test_pipeline_defaults_to_legacy_path_when_paths_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Create the legacy layout.
    (tmp_path / "src" / "lambda" / "orders").mkdir(parents=True)
    (tmp_path / "src" / "lambda" / "orders" / "handler.py").write_text("pass\n")
    pipe = MigrationPipeline(project_root=str(tmp_path))
    await pipe.initialize()

    with patch("agent_harness.pipeline.analyze_module",
               new=AsyncMock(return_value="analysis")) as azm, \
         patch("agent_harness.pipeline.propose_contract",
               new=AsyncMock(return_value="c")), \
         patch("agent_harness.pipeline.finalize_contract",
               new=AsyncMock(return_value="c")), \
         patch("agent_harness.pipeline.migrate_module",
               new=AsyncMock(return_value="m")), \
         patch("agent_harness.pipeline.evaluate_module",
               new=AsyncMock(return_value="PASS")), \
         patch("agent_harness.pipeline.review_module",
               new=AsyncMock(return_value={"recommendation": "APPROVE",
                                            "confidence_score": 90,
                                            "coverage": 80})), \
         patch("agent_harness.pipeline.security_review",
               new=AsyncMock(return_value={"recommendation": "APPROVE"})):
        await pipe.run(module="orders", language="python")

    # analyzer got NO source_paths (falls back to legacy dir).
    _, kwargs = azm.call_args
    assert kwargs.get("source_paths", []) == []
```

- [ ] **Step 2: Run test**

Run: `python3 -m pytest tests/test_pipeline_paths.py -v`
Expected: TypeError — `run` got unexpected keyword `source_paths`.

- [ ] **Step 3: Extend `MigrationPipeline.run`**

In `agent_harness/pipeline.py`, modify `MigrationPipeline.run` signature and its calls into analyzer/coder/tester.

Replace the signature:

```python
    async def run(
        self,
        module: str,
        language: str,
        work_item_id: str = "LOCAL",
        title: str = "",
        description: str = "",
        acceptance_criteria: str = "",
        source_paths: list[str] | tuple = (),
        context_paths: list[str] | tuple = (),
    ) -> PipelineResult:
```

Find the line that calls `analyze_module(...)`; change the call:

```python
                analysis = await analyze_module(
                    module=module, language=language, source_dir=source_dir,
                    source_paths=source_paths, context_paths=context_paths,
                )
```

Find the call to `migrate_module(...)`; change to:

```python
                await migrate_module(
                    module=module, language=language, source_dir=source_dir,
                    analysis_path=analysis, attempt=attempt,
                    source_paths=source_paths, context_paths=context_paths,
                )
```

Find the call to `evaluate_module(...)`; change to:

```python
                eval_result = await evaluate_module(
                    module=module, language=language, contract=contract,
                    attempt=attempt,
                    source_paths=source_paths, context_paths=context_paths,
                )
```

- [ ] **Step 4: Run tests (regression + new)**

Run: `python3 -m pytest tests/test_pipeline_paths.py tests/test_integration.py -v`
Expected: 2 new PASS. `test_integration.py` failures are pre-existing and unrelated.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/pipeline.py tests/test_pipeline_paths.py
git commit -m "feat(pipeline): MigrationPipeline.run plumbs source_paths/context_paths"
```

---

## Task 7: New `agent_harness/fanout.py` — `migrate_repo` orchestration

**Files:**
- Create: `agent_harness/fanout.py`
- Test: `tests/test_fanout.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fanout.py
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent_harness.discovery.artifacts import (
    AcceptanceCriterion, Backlog, BacklogItem, Epic, Story, Stories,
)
from agent_harness.discovery import paths as discovery_paths
from agent_harness.fanout import migrate_repo, RepoMigrationResult, ModuleOutcome
from agent_harness.persistence.repository import MigrationRepository
from agent_harness.pipeline import PipelineResult


def _write_artifacts(tmp_path, backlog_items, stories_pairs):
    repo_dir = tmp_path / "discovery" / "synth"
    repo_dir.mkdir(parents=True, exist_ok=True)
    backlog = Backlog(items=backlog_items)
    (repo_dir / "backlog.json").write_text(backlog.model_dump_json())
    stories = Stories(
        epics=[Epic(id=f"E-{m}", module_id=m, title="E",
                    story_ids=[sid])
               for (m, sid, _deps) in stories_pairs],
        stories=[Story(id=sid, epic_id=f"E-{m}", title="t", description="d",
                       acceptance_criteria=[AcceptanceCriterion(text="ac")],
                       depends_on=list(deps), blocks=[], estimate="M")
                 for (m, sid, deps) in stories_pairs],
    )
    (repo_dir / "stories.json").write_text(stories.model_dump_json())


def _item(module, wave, sid):
    return BacklogItem(module=module, language="python", work_item_id=sid,
                       title="", description="", acceptance_criteria="",
                       wave=wave)


@pytest.fixture
def repo(tmp_path):
    r = MigrationRepository(db_path=tmp_path / "t.db")
    r.initialize()
    r.create_discovery_run("synth")
    r.approve_backlog("synth", approver="tester")
    return r


@pytest.fixture
def pipeline_stub():
    p = AsyncMock()
    p.run = AsyncMock(return_value=PipelineResult(
        module="orders", status="completed", message="", review_score=90,
    ))
    return p


@pytest.mark.asyncio
async def test_unapproved_backlog_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = MigrationRepository(db_path=tmp_path / "t.db")
    r.initialize()
    r.create_discovery_run("synth")  # not approved
    _write_artifacts(tmp_path, [_item("orders", 1, "S1")],
                     [("orders", "S1", [])])
    p = AsyncMock()
    with pytest.raises(PermissionError):
        await migrate_repo(repo_id="synth", repo=r, pipeline=p)


@pytest.mark.asyncio
async def test_missing_backlog_raises(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    p = AsyncMock()
    with pytest.raises(FileNotFoundError):
        await migrate_repo(repo_id="synth", repo=repo, pipeline=p)


@pytest.mark.asyncio
async def test_all_modules_complete(tmp_path, monkeypatch, repo, pipeline_stub):
    monkeypatch.chdir(tmp_path)
    _write_artifacts(tmp_path,
        [_item("orders", 1, "S1"), _item("payments", 2, "S2")],
        [("orders", "S1", []), ("payments", "S2", ["S1"])])
    result = await migrate_repo(repo_id="synth", repo=repo, pipeline=pipeline_stub)
    assert result.status == "completed"
    assert {m.module: m.status for m in result.modules} == {
        "orders": "completed", "payments": "completed"
    }
    assert pipeline_stub.run.await_count == 2


@pytest.mark.asyncio
async def test_failure_propagates_skip_to_dependent(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    _write_artifacts(tmp_path,
        [_item("orders", 1, "S1"),
         _item("payments", 2, "S2"),
         _item("notifications", 2, "S3")],
        [("orders", "S1", []),
         ("payments", "S2", ["S1"]),      # depends on orders
         ("notifications", "S3", [])])    # independent

    def fake_result(module, **_):
        if module == "orders":
            return PipelineResult(module="orders", status="failed",
                                  message="boom", review_score=None)
        return PipelineResult(module=module, status="completed",
                              message="", review_score=80)

    p = AsyncMock()
    p.run = AsyncMock(side_effect=lambda module, **kw: fake_result(module, **kw))

    result = await migrate_repo(repo_id="synth", repo=repo, pipeline=p)
    by_mod = {m.module: m for m in result.modules}
    assert by_mod["orders"].status == "failed"
    assert by_mod["payments"].status == "skipped"
    assert "S1" in by_mod["payments"].reason
    assert by_mod["notifications"].status == "completed"
    assert result.status == "partial"
    # pipeline.run should NOT have been called for payments (skipped).
    called_modules = {c.kwargs.get("module") for c in p.run.await_args_list}
    assert "payments" not in called_modules


@pytest.mark.asyncio
async def test_intra_wave_concurrency(tmp_path, monkeypatch, repo):
    """Two independent modules in the same wave should run in parallel."""
    monkeypatch.chdir(tmp_path)
    _write_artifacts(tmp_path,
        [_item("a", 1, "SA"), _item("b", 1, "SB")],
        [("a", "SA", []), ("b", "SB", [])])

    both_entered = asyncio.Event()
    entered = {"count": 0}

    async def slow_run(module, **_):
        entered["count"] += 1
        if entered["count"] == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=1.0)
        return PipelineResult(module=module, status="completed",
                              message="", review_score=85)

    p = AsyncMock()
    p.run = AsyncMock(side_effect=slow_run)
    result = await migrate_repo(repo_id="synth", repo=repo, pipeline=p)
    assert result.status == "completed"
    # Both entered before either returned = real concurrency.
    assert both_entered.is_set()


@pytest.mark.asyncio
async def test_persists_outcomes(tmp_path, monkeypatch, repo, pipeline_stub):
    monkeypatch.chdir(tmp_path)
    _write_artifacts(tmp_path, [_item("orders", 1, "S1")],
                     [("orders", "S1", [])])
    await migrate_repo(repo_id="synth", repo=repo, pipeline=pipeline_stub)
    run = repo.get_migrate_repo_run("synth")
    assert run["status"] == "completed"
    assert len(run["modules"]) == 1
    assert run["modules"][0]["status"] == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_fanout.py -v`
Expected: ImportError — `agent_harness.fanout` module does not exist.

- [ ] **Step 3: Implement `fanout.py`**

```python
# agent_harness/fanout.py
"""Fan out an approved backlog to the migration pipeline, wave by wave."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .discovery import paths as discovery_paths
from .discovery.artifacts import Backlog, BacklogItem, Stories
from .persistence.repository import MigrationRepository

logger = logging.getLogger("fanout")


@dataclass
class ModuleOutcome:
    module: str
    wave: int
    status: Literal["completed", "failed", "skipped"]
    reason: str = ""
    review_score: int | None = None


@dataclass
class RepoMigrationResult:
    repo_id: str
    run_id: int
    status: Literal["completed", "partial", "failed"]
    modules: list[ModuleOutcome] = field(default_factory=list)


async def migrate_repo(
    repo_id: str,
    repo: MigrationRepository,
    pipeline,
    semaphore: asyncio.Semaphore | None = None,
) -> RepoMigrationResult:
    """Fan out an approved backlog to pipeline.run, wave by wave.

    Concurrent within a wave, continue-on-error. Descendants of failed
    modules (via stories.json depends_on) are marked skipped.
    """
    if not repo.is_backlog_approved(repo_id):
        raise PermissionError(
            f"backlog for {repo_id} is not approved; call /approve/backlog/{repo_id}"
        )

    backlog_path = discovery_paths.backlog_path(repo_id)
    stories_path = discovery_paths.stories_path(repo_id)
    if not backlog_path.exists():
        raise FileNotFoundError(f"backlog missing: {backlog_path}")
    if not stories_path.exists():
        raise FileNotFoundError(f"stories missing: {stories_path}")

    backlog = Backlog.model_validate_json(backlog_path.read_text())
    stories = Stories.model_validate_json(stories_path.read_text())

    run_id = repo.create_migrate_repo_run(repo_id)

    # Build dependency closure on story ids.
    dependents: dict[str, set[str]] = defaultdict(set)
    for s in stories.stories:
        for dep in s.depends_on:
            dependents[dep].add(s.id)
    # story_id -> backlog item (work_item_id is the story id).
    item_by_story = {it.work_item_id: it for it in backlog.items}

    by_wave: dict[int, list[BacklogItem]] = defaultdict(list)
    for it in backlog.items:
        by_wave[it.wave].append(it)

    outcomes: dict[str, ModuleOutcome] = {}
    failed_story_ids: set[str] = set()
    skipped_because: dict[str, str] = {}  # story_id -> failed_or_skipped ancestor

    for wave in sorted(by_wave):
        wave_items = by_wave[wave]

        async def _run(it: BacklogItem) -> ModuleOutcome:
            # Skip if any transitive dependency failed/skipped.
            blocker = _first_blocked_dep(it, stories, failed_story_ids,
                                          skipped_because)
            if blocker:
                outcome = ModuleOutcome(
                    module=it.module, wave=wave,
                    status="skipped", reason=f"{blocker} failed or skipped",
                )
                repo.record_migrate_module(run_id, it.module, wave,
                                            status="skipped", reason=outcome.reason)
                return outcome

            repo.record_migrate_module(run_id, it.module, wave, status="running")
            sem = semaphore or _noop_semaphore()
            try:
                async with sem:
                    result = await pipeline.run(
                        module=it.module, language=it.language,
                        work_item_id=it.work_item_id, title=it.title,
                        description=it.description,
                        acceptance_criteria=it.acceptance_criteria,
                        source_paths=it.source_paths,
                        context_paths=it.context_paths,
                    )
            except Exception as exc:
                logger.exception("pipeline crashed on %s", it.module)
                outcome = ModuleOutcome(module=it.module, wave=wave,
                                         status="failed",
                                         reason=f"exception: {exc!r}")
                repo.record_migrate_module(run_id, it.module, wave,
                                            status="failed",
                                            reason=outcome.reason)
                return outcome

            if result.status == "completed":
                outcome = ModuleOutcome(module=it.module, wave=wave,
                                         status="completed",
                                         review_score=result.review_score)
            else:
                outcome = ModuleOutcome(module=it.module, wave=wave,
                                         status="failed",
                                         reason=result.message or result.status)
            repo.record_migrate_module(
                run_id, it.module, wave,
                status=outcome.status, reason=outcome.reason,
                review_score=outcome.review_score,
            )
            return outcome

        results = await asyncio.gather(*(_run(it) for it in wave_items))
        for it, outcome in zip(wave_items, results):
            outcomes[it.work_item_id] = outcome
            if outcome.status == "failed":
                failed_story_ids.add(it.work_item_id)
            elif outcome.status == "skipped":
                skipped_because[it.work_item_id] = outcome.reason

    module_list = [outcomes[it.work_item_id] for it in backlog.items]
    all_completed = all(o.status == "completed" for o in module_list)
    any_completed = any(o.status == "completed" for o in module_list)
    status = "completed" if all_completed else ("partial" if any_completed else "failed")
    # Empty backlog → completed (spec §7).
    if not module_list:
        status = "completed"
    repo.complete_migrate_repo_run(run_id, status)
    return RepoMigrationResult(repo_id=repo_id, run_id=run_id,
                               status=status, modules=module_list)


def _first_blocked_dep(item: BacklogItem, stories: Stories,
                       failed: set[str], skipped: dict[str, str]) -> str | None:
    """Walk transitive depends_on; return the first failed/skipped ancestor id."""
    by_id = {s.id: s for s in stories.stories}
    stack = list(by_id[item.work_item_id].depends_on) if item.work_item_id in by_id else []
    seen: set[str] = set()
    while stack:
        dep = stack.pop()
        if dep in seen:
            continue
        seen.add(dep)
        if dep in failed or dep in skipped:
            return dep
        if dep in by_id:
            stack.extend(by_id[dep].depends_on)
    return None


class _noop_semaphore:
    """Async context manager that does nothing — used when no semaphore is supplied."""
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_fanout.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/fanout.py tests/test_fanout.py
git commit -m "feat(fanout): migrate_repo orchestrator with wave/skip semantics"
```

---

## Task 8: FastAPI endpoints — `/migrate-repo`, `/migrate-repo/sync`, `GET /migrate-repo/{repo_id}`

**Files:**
- Modify: `agent_harness/orchestrator/api.py`
- Test: `tests/test_migrate_repo_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrate_repo_api.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agent_harness.fanout import RepoMigrationResult, ModuleOutcome


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from agent_harness.orchestrator import api as api_mod
    api_mod._pipeline = None  # real pipeline not needed; mocked
    api_mod._ado = None
    from agent_harness.persistence.repository import MigrationRepository
    api_mod._discovery_repo = MigrationRepository(db_path=tmp_path / "disc.db")
    api_mod._discovery_repo.initialize()
    return TestClient(api_mod.app)


def test_migrate_repo_sync_not_approved_returns_409(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    resp = client.post("/migrate-repo/sync", json={"repo_id": "synth"})
    assert resp.status_code == 409


def test_migrate_repo_sync_returns_result(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    api_mod._discovery_repo.approve_backlog("synth", approver="t")

    fake = RepoMigrationResult(repo_id="synth", run_id=1, status="completed",
        modules=[ModuleOutcome(module="orders", wave=1, status="completed",
                                review_score=80)])
    with patch("agent_harness.fanout.migrate_repo",
               new=AsyncMock(return_value=fake)):
        resp = client.post("/migrate-repo/sync", json={"repo_id": "synth"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["modules"][0]["module"] == "orders"


def test_migrate_repo_background_returns_accepted(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    api_mod._discovery_repo.approve_backlog("synth", approver="t")

    fake = RepoMigrationResult(repo_id="synth", run_id=1, status="completed", modules=[])
    with patch("agent_harness.fanout.migrate_repo",
               new=AsyncMock(return_value=fake)):
        resp = client.post("/migrate-repo", json={"repo_id": "synth"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


def test_migrate_repo_background_rejects_unapproved(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    resp = client.post("/migrate-repo", json={"repo_id": "synth"})
    assert resp.status_code == 409


def test_get_migrate_repo_404_when_no_run(client):
    resp = client.get("/migrate-repo/unknown")
    assert resp.status_code == 404


def test_get_migrate_repo_returns_run(client):
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.create_discovery_run("synth")
    run_id = api_mod._discovery_repo.create_migrate_repo_run("synth")
    api_mod._discovery_repo.record_migrate_module(run_id, "orders", wave=1,
                                                   status="completed",
                                                   review_score=90)
    resp = client.get("/migrate-repo/synth")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo_id"] == "synth"
    assert body["modules"][0]["module"] == "orders"
```

- [ ] **Step 2: Run test**

Run: `python3 -m pytest tests/test_migrate_repo_api.py -v`
Expected: 404/Not Found for all endpoints.

- [ ] **Step 3: Add new models + endpoints**

At the bottom of `agent_harness/orchestrator/api.py`, append:

```python
from agent_harness import fanout as _fanout


class MigrateRepoRequest(BaseModel):
    repo_id: str


class MigrateRepoModuleStatus(BaseModel):
    module: str
    wave: int
    status: str
    reason: str = ""
    review_score: int | None = None


class MigrateRepoResultBody(BaseModel):
    repo_id: str
    run_id: int
    status: str
    modules: list[MigrateRepoModuleStatus] = Field(default_factory=list)


class MigrateRepoAcceptedBody(BaseModel):
    repo_id: str
    run_id: int | None = None
    status: str = "accepted"


class MigrateRepoRunBody(BaseModel):
    repo_id: str
    id: int | None = None
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    modules: list[MigrateRepoModuleStatus] = Field(default_factory=list)


def _assert_approved_or_409(repo_id: str) -> None:
    if not _discovery_repo.is_backlog_approved(repo_id):
        raise HTTPException(409,
            f"backlog for {repo_id} is not approved; call /approve/backlog/{repo_id}")


@app.post("/migrate-repo", response_model=MigrateRepoAcceptedBody)
async def migrate_repo_async(req: MigrateRepoRequest, bg: BackgroundTasks):
    _assert_approved_or_409(req.repo_id)

    async def _run():
        try:
            await _fanout.migrate_repo(repo_id=req.repo_id,
                                        repo=_discovery_repo,
                                        pipeline=_pipeline)
        except Exception:
            logger.exception("migrate_repo background task failed")

    bg.add_task(_run)
    return MigrateRepoAcceptedBody(repo_id=req.repo_id)


@app.post("/migrate-repo/sync", response_model=MigrateRepoResultBody)
async def migrate_repo_sync(req: MigrateRepoRequest):
    _assert_approved_or_409(req.repo_id)
    try:
        result = await _fanout.migrate_repo(
            repo_id=req.repo_id, repo=_discovery_repo, pipeline=_pipeline,
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return MigrateRepoResultBody(
        repo_id=result.repo_id, run_id=result.run_id, status=result.status,
        modules=[MigrateRepoModuleStatus(**vars(m)) for m in result.modules],
    )


@app.get("/migrate-repo/{repo_id}", response_model=MigrateRepoRunBody)
async def get_migrate_repo(repo_id: str):
    run = _discovery_repo.get_migrate_repo_run(repo_id)
    if run is None:
        raise HTTPException(404, f"no migrate-repo run for {repo_id}")
    return MigrateRepoRunBody(
        repo_id=repo_id, id=run.get("id"),
        status=run.get("status"),
        started_at=run.get("started_at"),
        completed_at=run.get("completed_at"),
        modules=[MigrateRepoModuleStatus(**m) for m in run.get("modules", [])],
    )
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_migrate_repo_api.py tests/test_discovery_api.py tests/test_migrate_request_paths.py -v`
Expected: 6 new + 5 discovery + 4 request = 15 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/orchestrator/api.py tests/test_migrate_repo_api.py
git commit -m "feat(orchestrator): /migrate-repo, /migrate-repo/sync, GET /migrate-repo/{repo_id}"
```

---

## Task 9: End-to-end integration test

**Files:**
- Test: `tests/test_fanout_e2e.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_fanout_e2e.py
"""Discover → plan → approve → migrate-repo/sync against the synthetic fixture."""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, Stories, Story, Epic, AcceptanceCriterion,
)
from agent_harness.discovery import paths as discovery_paths
from agent_harness.discovery.workflow import run_discovery, run_planning
from agent_harness.fanout import migrate_repo
from agent_harness.persistence.repository import MigrationRepository
from agent_harness.pipeline import PipelineResult

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


def _brd_body(refs: list[str]) -> str:
    side = "\n".join(f"- writes/reads {r}" for r in refs)
    return (
        "## Purpose\nx\n\n## Triggers\nx\n\n## Inputs\nx\n\n## Outputs\nx\n\n"
        "## Business Rules\n- r\n\n"
        f"## Side Effects\n{side}\n\n"
        "## Error Paths\n- e\n\n## Non-Functionals\n- n\n\n## PII/Compliance\n- n\n"
    )


def _design_body(refs: list[str]) -> str:
    sm = "\n".join(f"- {r} → Azure target" for r in refs)
    return (
        "## Function Plan\nFlex\n\n## Trigger Bindings\n- HTTP\n\n"
        f"## State Mapping\n{sm}\n\n## Secrets\n- KV\n\n"
        "## Identity\n- MI\n\n## IaC\n- Bicep\n\n## Observability\n- AI\n"
    )


@pytest.mark.asyncio
async def test_discover_plan_approve_migrate_repo_e2e(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = MigrationRepository(db_path=tmp_path / "e2e.db")
    repo.initialize()

    inv_json = Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 8, "total_loc": 60,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py", loc=14, config_files=[]),
            ModuleRecord(id="payments", path="payments", language="python",
                         handler_entrypoint="payments/handler.py", loc=18, config_files=[]),
            ModuleRecord(id="notifications", path="notifications", language="python",
                         handler_entrypoint="notifications/handler.py", loc=12, config_files=[]),
        ],
    ).model_dump_json()

    brd_canned = {
        "orders": _brd_body(["dynamodb_table:Orders", "sqs_queue:payments-queue"]),
        "payments": _brd_body(["dynamodb_table:Orders", "dynamodb_table:Payments",
                               "sns_topic:payment-events"]),
        "notifications": _brd_body(["secrets_manager_secret:webhook/url"]),
    }
    design_canned = {
        "orders": _design_body(["dynamodb_table:Orders", "sqs_queue:payments-queue"]),
        "payments": _design_body(["dynamodb_table:Orders", "dynamodb_table:Payments",
                                  "sns_topic:payment-events"]),
        "notifications": _design_body(["secrets_manager_secret:webhook/url"]),
    }
    stories_canned = Stories(
        epics=[Epic(id="E1", module_id="orders", title="o", story_ids=["S1"]),
               Epic(id="E2", module_id="payments", title="p", story_ids=["S2"]),
               Epic(id="E3", module_id="notifications", title="n", story_ids=["S3"])],
        stories=[
            Story(id="S1", epic_id="E1", title="o", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=[], blocks=[], estimate="M"),
            Story(id="S2", epic_id="E2", title="p", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S1"], blocks=[], estimate="M"),
            Story(id="S3", epic_id="E3", title="n", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S2"], blocks=[], estimate="M"),
        ],
    ).model_dump_json()

    async def _brd_side(message):
        for mid, body in brd_canned.items():
            if f"`{mid}`" in message:
                return body
        return "## Business Rules\n- r\n## Error Paths\n- e\n## Side Effects\n- none\n"

    async def _design_side(message):
        for mid, body in design_canned.items():
            if f"`{mid}`" in message:
                return body
        return "## State Mapping\n- none\n"

    with patch("agent_harness.discovery.repo_scanner._run_agent",
               new=AsyncMock(return_value=inv_json)), \
         patch("agent_harness.discovery.dependency_grapher._run_agent",
               new=AsyncMock(return_value="[]")), \
         patch("agent_harness.discovery.brd_extractor._run_module_agent",
               side_effect=_brd_side), \
         patch("agent_harness.discovery.brd_extractor._run_system_agent",
               new=AsyncMock(return_value="# System BRD\nok")), \
         patch("agent_harness.discovery.architect._run_module_agent",
               side_effect=_design_side), \
         patch("agent_harness.discovery.architect._run_system_agent",
               new=AsyncMock(return_value="# System Design\nok")), \
         patch("agent_harness.discovery.story_decomposer._run_agent",
               new=AsyncMock(return_value=stories_canned)):
        await run_discovery(repo_id="synth", repo_path=str(FIXTURE), repo=repo)

    backlog = await run_planning(repo_id="synth", repo=repo)
    # Each backlog item must carry the module's handler file as source_paths.
    for item in backlog.items:
        assert item.source_paths, f"source_paths empty for {item.module}"
        assert str(FIXTURE) in item.source_paths[0]

    repo.approve_backlog("synth", approver="tester")

    # Stub the pipeline — verify every module gets its own call with the right paths.
    pipeline = AsyncMock()
    pipeline.run = AsyncMock(side_effect=lambda module, **kw: PipelineResult(
        module=module, status="completed", message="", review_score=85,
    ))

    result = await migrate_repo(repo_id="synth", repo=repo, pipeline=pipeline)
    assert result.status == "completed"
    by_mod = {m.module: m for m in result.modules}
    assert set(by_mod) == {"orders", "payments", "notifications"}
    assert all(m.status == "completed" for m in result.modules)
    assert pipeline.run.await_count == 3

    # Each pipeline call received non-empty source_paths.
    for call in pipeline.run.await_args_list:
        assert call.kwargs["source_paths"], \
            f"pipeline.run called without source_paths for {call.kwargs['module']}"
```

- [ ] **Step 2: Run test**

Run: `python3 -m pytest tests/test_fanout_e2e.py -v`
Expected: 1 PASS.

- [ ] **Step 3: Run full discovery + fanout suite for regression**

Run:
```
python3 -m pytest \
  tests/test_discovery_artifacts.py tests/test_discovery_repository.py \
  tests/test_tree_sitter_py.py tests/test_aws_sdk_patterns.py \
  tests/test_graph_io.py tests/test_wave_scheduler.py \
  tests/test_repo_scanner.py tests/test_dependency_grapher.py \
  tests/test_brd_extractor.py tests/test_architect.py \
  tests/test_story_decomposer.py tests/test_discovery_workflow.py \
  tests/test_discovery_api.py tests/test_discovery_e2e.py \
  tests/test_backlog_item_paths.py tests/test_migrate_repo_repository.py \
  tests/test_wave_scheduler_paths.py tests/test_migrate_request_paths.py \
  tests/test_pipeline_paths.py tests/test_fanout.py \
  tests/test_migrate_repo_api.py tests/test_fanout_e2e.py -q
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_fanout_e2e.py
git commit -m "test(fanout): end-to-end discover→plan→approve→migrate-repo"
```

---

## Task 10: README — fanout workflow

**Files:**
- Modify: `README.md` (at `ms-agent-harness/README.md`)

- [ ] **Step 1: Append a new section**

Append to `README.md`:

```markdown
## Multi-Module Migration (Fanout)

After discovery approves a backlog, fan it out to the pipeline wave by wave:

- `POST /migrate-repo {repo_id}` — background fanout. Returns `{repo_id, status:"accepted"}`.
- `POST /migrate-repo/sync {repo_id}` — synchronous; returns per-module result list.
- `GET /migrate-repo/{repo_id}` — latest run progress with per-module wave + status.

Guardrails:
- 409 if `/approve/backlog/{repo_id}` has not been called.
- Modules run concurrently within a wave under the global
  `MAX_CONCURRENT_MIGRATIONS` semaphore.
- If a module fails, its transitive dependents (by `stories.json` `depends_on`)
  are marked `skipped`; independent branches continue.

Each backlog item carries `source_paths` (the handler file to migrate) and
`context_paths` (shared helpers the handler imports but the current run
is not migrating — passed to the agent as read-only anti-corruption
boundary). This lets the pipeline ingest arbitrary repo layouts without the
legacy `src/lambda/<module>/` staging requirement.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(fanout): document /migrate-repo endpoints and fanout semantics"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 = §4.1. Task 2 = §4.7. Task 3 = §4.2. Task 4 = §4.3. Task 5 = §4.5. Task 6 = §4.4. Task 7 = §4.6. Task 8 = §4.8. Task 9 = §8 integration. Task 10 = user-visible surface.
- **Approval gate (§6.3):** enforced in both `fanout.migrate_repo` (raises `PermissionError`) and at the API layer (`_assert_approved_or_409`). Task 7 test covers it; Task 8 tests the 409 mapping.
- **Error-code map (§7):** unapproved → 409 (Task 8 test), missing backlog → 404 (Task 7 test), missing source path → 404 (Task 4 test), pipeline exception → row `failed` + continue (Task 7 test via `side_effect` raising).
- **Type consistency:** `source_paths` and `context_paths` are `list[str] | tuple = ()` everywhere (analyzer/coder/tester/pipeline). `BacklogItem` uses `list[str] = Field(default_factory=list)` because Pydantic doesn't accept tuple defaults for `list[str]`. Both are JSON-serialisable as lists.
- **Descendant-skip correctness:** `_first_blocked_dep` in `fanout.py` walks transitive `depends_on` using the story DAG — matches §6.2.
- **Back-compat:** `test_legacy_backlog_item_still_loads` (Task 1), `test_legacy_request_still_404s_when_src_lambda_missing` (Task 4), `test_pipeline_defaults_to_legacy_path_when_paths_empty` (Task 6) all assert the v1 behaviour is preserved.
