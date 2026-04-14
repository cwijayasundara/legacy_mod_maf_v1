# Migration Fanout (Sub-project B) — Design Spec

**Date:** 2026-04-14
**Status:** Draft — pending review
**Target repo:** `ms-agent-harness`
**Depends on:** `2026-04-14-discovery-planning-layer-design.md` (sub-project A, already merged)

---

## 1. Context

Sub-project A (Discovery & Planning) produces an approved `backlog.json` at
`ms-agent-harness/discovery/<repo_id>/backlog.json`. Each item in that backlog
matches the schema accepted by the existing `POST /migrate` endpoint and carries
a `wave: int` for topological ordering.

What's missing:

1. **Auto-fanout.** There is no endpoint that consumes an approved backlog and
   dispatches `/migrate` per module wave by wave.
2. **Path flexibility.** The existing `/migrate` hard-codes the source path as
   `PROJECT_ROOT/src/lambda/<module>/`. Real repos have other layouts — e.g.
   a single Python package where handlers live at `handlers/*.py` and shared
   code sits in `services/`. The current pipeline cannot ingest them.

This spec closes both gaps. It is sub-project B of the four-part decomposition.
Sub-projects C (evaluation framework) and D (harness hardening) remain deferred.

## 2. Scope

### In scope (v1 of this sub-project)

- Extend `BacklogItem` with `source_paths` and `context_paths`.
- Extend `WaveScheduler` to populate those fields from the inventory + graph.
- Extend `MigrationRequest`, `MigrationPipeline.run`, `analyzer`, `coder`,
  `tester` to accept explicit paths and bypass the `src/lambda/` lookup when
  present.
- New `agent_harness/fanout.py` — `async migrate_repo(...)` with wave-by-wave,
  concurrent-within-wave, continue-on-error semantics.
- Three new FastAPI endpoints: `POST /migrate-repo`, `POST /migrate-repo/sync`,
  `GET /migrate-repo/{repo_id}`.
- Two new SQLite tables: `migrate_repo_runs`, `migrate_repo_module_runs`.
- Approval gate: fanout refuses to run unless `discovery_runs.approved = 1`.
- Unit + mocked-LLM integration tests over the existing synthetic fixture.

### Out of scope (future work)

- Real Azure deployment of migrated functions (sub-project D).
- Cross-module integration tests post-migration (sub-project C).
- Migration of the shared services package itself — v1 treats it as read-only
  context (strangler-fig day-one posture). A future wave can migrate it.
- Streaming/SSE progress, cancellation, per-module restart.
- Heuristic inclusion of sibling source files in `source_paths` — v1 migrates
  exactly the handler entrypoint; everything else is context.
- Parallelism across repos (the existing `MAX_CONCURRENT_MIGRATIONS` semaphore
  still bounds the process-wide budget).

## 3. Architecture

### 3.1 Placement

```
ms-agent-harness/
└── agent_harness/
    ├── analyzer.py             [modify] accept extra context dirs
    ├── coder.py                [modify] accept extra context dirs
    ├── tester.py               [modify] accept extra context dirs
    ├── pipeline.py             [modify] accept source_paths + context_paths
    ├── fanout.py               [NEW]    async migrate_repo(...)
    ├── orchestrator/api.py     [modify] + /migrate-repo endpoints, MigrationRequest fields
    ├── persistence/
    │   └── repository.py       [modify] + migrate_repo_runs + migrate_repo_module_runs
    └── discovery/
        ├── artifacts.py        [modify] BacklogItem gains source_paths + context_paths
        └── wave_scheduler.py   [modify] schedule() also takes inventory + graph, populates paths
```

### 3.2 Reuse of existing infrastructure

- `MigrationPipeline.run` remains the single per-module entry point. Fanout
  calls it once per backlog item with explicit paths.
- `MigrationRepository._connect` / `initialize` extend to the two new tables.
- `MAX_CONCURRENT_MIGRATIONS` semaphore unchanged — fanout reuses it.
- Existing `/migrate` and `/migrate/sync` endpoints unchanged for back-compat.

## 4. Components

### 4.1 `artifacts.BacklogItem`

Add two optional fields (default empty list so existing data round-trips):

```python
source_paths: list[str] = Field(default_factory=list)
context_paths: list[str] = Field(default_factory=list)
```

Semantics:
- `source_paths` — absolute paths of files/dirs to migrate (copied into the
  migrator's working view, written into target Azure Function).
- `context_paths` — absolute paths shown to the migrator read-only. Includes
  siblings the handler imports but that are NOT being migrated in this run.

### 4.2 `WaveScheduler.schedule(stories, language_by_module, inventory, graph)`

Signature extended. For each `BacklogItem` produced:

1. Look up the inventory entry for `item.module`. Resolve
   `handler_entrypoint` against `inventory.repo_meta.root_path` → absolute
   path. Assign `source_paths = [that absolute path]`.
2. Walk `graph.edges` for `imports` edges with `src == item.module`.
3. For each imported target `T`:
   - If `T` is a module id present in the backlog → skip (it will be migrated
     on its own wave).
   - Else resolve the target's directory. If `T` is an inventory module, use
     `inventory.modules[T].path`. If `T` is not in the inventory (common for
     shared sub-packages like `services/`), use `T` as a path relative to
     `root_path`.
   - Glob `*.py` under that directory. Append absolute paths to
     `context_paths`.
4. Deduplicate `context_paths`.

When a backlog is produced from an inventory that doesn't include shared
sub-packages (the current scanner skips them), those sub-packages still end up
as edge targets in the graph — the grapher's head-segment heuristic emits an
import edge to `services` even though `services` isn't a module. This is the
hook the scheduler uses to include them as context.

### 4.3 `agent_harness/orchestrator/api.py` — `MigrationRequest` extension

Add the same two optional fields:

```python
source_paths: list[str] = Field(default_factory=list)
context_paths: list[str] = Field(default_factory=list)
```

`_validate` change:

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
    # Legacy behaviour: src/lambda/<module>/ under PROJECT_ROOT.
    source = os.path.join(PROJECT_ROOT, "src", "lambda", req.module)
    if not os.path.isdir(source):
        raise HTTPException(404, f"Lambda source not found at src/lambda/{req.module}/")
```

### 4.4 `MigrationPipeline.run(..., source_paths=None, context_paths=None)`

When `source_paths` is provided:
- Resolve `source_dir` to the common parent of `source_paths` (or
  `source_paths[0]`'s parent if a single file).
- Pass `source_paths` through to `analyzer`/`coder`/`tester` as a new
  `source_paths` kwarg, replacing their directory-rglob behaviour.
- Pass `context_paths` through as a new `context_paths` kwarg — each consumer
  includes those files read-only in its prompt with a "do not migrate"
  banner.
- All existing self-heal / review / security gates run unchanged.

When `source_paths` is `None`, legacy `src/lambda/<module>/` behaviour is
preserved (regression safety).

### 4.5 `analyzer.py` / `coder.py` / `tester.py` — minimal extension

Each `analyze_module` / `migrate_module` / `evaluate_module` gains two
optional kwargs (both default to `()`):

- `source_paths: list[str] = ()` — when set, replaces the directory-rglob
  behaviour; only these exact paths are listed as the source to migrate.
- `context_paths: list[str] = ()` — when set, included read-only in prompts:
  - Analyzer: appends to `source_listing` with `(read-only — do not migrate)` banner.
  - Coder: injects into the TDD prompt with instruction to treat the files
    as an anti-corruption boundary; generated Azure code may `import` from
    them but must not modify them.
  - Tester: sees them for evaluation prompt coverage.

No behaviour change when both kwargs are empty — legacy `source_dir` rglob
still runs.

### 4.6 `agent_harness/fanout.py` — new

Pure orchestration; no FastAPI coupling.

```python
@dataclass
class ModuleOutcome:
    module: str
    wave: int
    status: Literal["completed", "failed", "skipped"]
    reason: str = ""        # failure message or "skip due to <dep>"
    review_score: int | None = None

@dataclass
class RepoMigrationResult:
    repo_id: str
    run_id: int
    status: Literal["completed", "partial", "failed"]
    modules: list[ModuleOutcome]


async def migrate_repo(
    repo_id: str,
    repo: MigrationRepository,
    pipeline: MigrationPipeline,
    semaphore: asyncio.Semaphore | None = None,
) -> RepoMigrationResult:
    """Fan out an approved backlog to the migration pipeline.

    Raises:
        PermissionError: backlog not approved.
        FileNotFoundError: backlog.json missing.
    """
```

Algorithm:

1. `if not repo.is_backlog_approved(repo_id): raise PermissionError(...)`.
2. Load `backlog.json` (paths via `discovery.paths`). Raise
   `FileNotFoundError` if missing.
3. Load `stories.json` (for the depends_on DAG used by descendant-skip).
4. `run_id = repo.create_migrate_repo_run(repo_id)`.
5. Group items by `wave`. Iterate waves in ascending order.
6. For each wave: `await asyncio.gather(*(_run_one(...) for item in wave),
   return_exceptions=True)`.
7. `_run_one` acquires the shared `MAX_CONCURRENT_MIGRATIONS` semaphore,
   calls `pipeline.run(module, language, work_item_id, title, description,
   acceptance_criteria, source_paths, context_paths)`, records the outcome.
8. Before invoking `_run_one`, check `failed_or_skipped` set against the
   item's transitive `depends_on` in the story DAG; if any dependency is
   `failed`/`skipped`, mark this module `skipped:<dep_id>` and do not call
   the pipeline.
9. Persist each module outcome via `repo.record_migrate_module(run_id, ...)`.
10. Set `migrate_repo_runs.status` to `completed` (all modules completed),
    `partial` (any failed/skipped), or `failed` (no modules completed).

Concurrency note: the `asyncio.gather` within a wave preserves the existing
`MAX_CONCURRENT_MIGRATIONS` semaphore behaviour of `/migrate`. No new
semaphore is introduced.

### 4.7 Persistence — two new tables

```sql
CREATE TABLE IF NOT EXISTS migrate_repo_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running'  -- running|completed|partial|failed
);

CREATE TABLE IF NOT EXISTS migrate_repo_module_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_run_id INTEGER NOT NULL,
    module TEXT NOT NULL,
    wave INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending|running|completed|failed|skipped
    reason TEXT DEFAULT '',
    review_score INTEGER,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_mrr_repo ON migrate_repo_runs(repo_id);
CREATE INDEX IF NOT EXISTS idx_mrmr_run ON migrate_repo_module_runs(repo_run_id);
```

New `MigrationRepository` methods:

- `create_migrate_repo_run(repo_id: str) -> int`
- `record_migrate_module(run_id, module, wave, status, reason='', review_score=None)`
- `complete_migrate_repo_run(run_id, status)`
- `get_migrate_repo_run(repo_id) -> dict | None` — returns latest run + its module rows for `GET /migrate-repo/{repo_id}`.

### 4.8 Endpoints

- `POST /migrate-repo {repo_id}` → background task that invokes `migrate_repo`.
  Returns `{repo_id, run_id, status: "accepted"}`. 409 if not approved.
  404 if backlog missing.
- `POST /migrate-repo/sync {repo_id}` → `await migrate_repo(...)`, returns
  `RepoMigrationResult` body.
- `GET /migrate-repo/{repo_id}` → latest run + module rows. 404 if no run.

## 5. Data contracts

### 5.1 Backlog item (v2, back-compat with v1)

```json
{
  "module": "orders",
  "language": "python",
  "work_item_id": "S1",
  "title": "Migrate orders",
  "description": "...",
  "acceptance_criteria": "...",
  "wave": 1,
  "source_paths": ["/abs/path/to/orders/handler.py"],
  "context_paths": ["/abs/path/to/services/aws_clients.py",
                    "/abs/path/to/services/helper.py"]
}
```

v1 backlogs (without the two new fields) still load — fields default to `[]`
and fanout falls back to legacy `src/lambda/<module>/`.

### 5.2 `RepoMigrationResult`

```json
{
  "repo_id": "legacy",
  "run_id": 42,
  "status": "partial",
  "modules": [
    {"module": "orders", "wave": 1, "status": "completed", "review_score": 87},
    {"module": "payments", "wave": 2, "status": "failed",
     "reason": "Blocked after 3 self-healing attempts"},
    {"module": "notifications", "wave": 2, "status": "completed",
     "review_score": 82}
  ]
}
```

## 6. Control flow

### 6.1 Happy path

```
/discover → /plan (backlog now carries source+context paths)
        → /approve/backlog/{repo_id}
        → POST /migrate-repo {repo_id}
           ├─ is_backlog_approved? no → 409
           ├─ backlog.json exists? no → 404
           ├─ create migrate_repo_runs row (status=running)
           ├─ for wave in sorted(waves):
           │    await asyncio.gather(_run_one(item) for item in wave)
           └─ finalize migrate_repo_runs.status = completed|partial|failed
```

### 6.2 Failure propagation

On a module failure at wave N, the descendant-skip pass walks `stories.json`
`depends_on`:

- Build reverse map `story_id → [dependents]`.
- When a module fails, mark all transitive dependents in future waves as
  `skipped:<failed_story_id>`.
- Record in `migrate_repo_module_runs`. Do not call `pipeline.run` for
  skipped items.

Independent branches (e.g. `notifications` with no dep on `orders`) continue
unaffected.

### 6.3 Approval gate

Enforced at the persistence layer via
`repo.is_backlog_approved(repo_id)` — same check the discovery layer exposes.
Fanout raises `PermissionError`, API handler maps to 409. Not a soft check in
the handler alone.

## 7. Error handling

| Condition                          | Behaviour                                  |
|------------------------------------|--------------------------------------------|
| Backlog not approved               | `PermissionError` → 409 Conflict           |
| `backlog.json` missing             | `FileNotFoundError` → 404                  |
| `stories.json` missing             | `FileNotFoundError` → 404 (needed for skip)|
| `source_paths` path missing        | 404 at `/migrate-repo` validation          |
| Pipeline raises inside a module    | row = `failed` + reason; fanout continues  |
| Pipeline returns `blocked`         | row = `failed` + reason = blocked message  |
| Dependency failed earlier in run   | descendant row = `skipped:<dep>`           |
| No backlog items                   | `RepoMigrationResult(status="completed", modules=[])` |

## 8. Testing

Mirrors the existing `tests/` layout.

### Unit (no LLM, fast)

- `test_wave_scheduler_paths.py` — new test cases for `schedule()` given the
  synthetic inventory + graph; assert `source_paths`, `context_paths` contents.
- `test_fanout.py` — mock `MigrationPipeline` (AsyncMock on `.run`). Cases:
  - linear chain, no failures → waves execute in order, all complete.
  - failure in wave 1 → transitive dependent in wave 2 is `skipped`,
    independent branch completes.
  - unapproved backlog → `PermissionError` raised.
  - missing backlog.json → `FileNotFoundError`.
  - within-wave concurrency honoured (use an `asyncio.Event` to prove parallel
    entry into `pipeline.run`).
- `test_migrate_repo_repository.py` — CRUD on the two new tables.

### Integration (mocked LLM)

- Extend the existing `test_discovery_e2e.py`-style fixture to run
  `/discover` → `/plan` → `/approve` → `/migrate-repo/sync` against the
  synthetic repo. Assert all 3 modules complete when pipeline is mocked to
  succeed; assert skip propagation when one mock raises.

### Regression

- Existing `test_discovery_e2e.py` must still pass (BacklogItem additions are
  optional).
- Existing `tests/test_integration.py` must still pass (MigrationPipeline new
  kwargs are optional).

## 9. Migration plan (how this ships)

1. Extend `BacklogItem` + WaveScheduler signature + unit tests.
2. New SQLite tables + repo methods + unit tests.
3. Extend `MigrationRequest` + `/migrate` validation. Existing `/migrate`
   call path stays green.
4. Extend `MigrationPipeline.run` + analyzer/coder/tester kwargs + unit
   regression test.
5. New `agent_harness/fanout.py` + unit tests with mocked pipeline.
6. New endpoints + integration test (mocked LLM end-to-end).
7. Update `README.md` Discovery section with the fanout workflow.

Each step is independently testable; order minimises blocking of the
downstream steps.

## 10. Open questions (none blocking)

- Should `migrate_repo_runs` retain history or keep only the latest run per
  `repo_id`? Leaning: retain history; `GET /migrate-repo/{repo_id}` returns
  latest, a future `/migrate-repo/{repo_id}/history` lists all.
- Should concurrency within a wave be capped below
  `MAX_CONCURRENT_MIGRATIONS`? Leaning: reuse the global semaphore, no new
  knob.

Both decisions are non-blocking and can be revisited in implementation.

---

**Next step:** user reviews, then implementation plan via `writing-plans`.
