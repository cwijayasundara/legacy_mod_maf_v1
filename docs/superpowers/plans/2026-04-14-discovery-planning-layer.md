# Discovery & Planning Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a discovery & planning subpackage to `ms-agent-harness` that inventories a multi-module Python repo, builds a code+AWS dependency graph, extracts BRDs, drafts Azure designs, decomposes work into stories, and produces a wave-ordered backlog consumable by the existing `/migrate` endpoint.

**Architecture:** New `agent_harness/discovery/` subpackage. 5 LLM-driven specialist agents (RepoScanner → DependencyGrapher → BRDExtractor → Architect → StoryDecomposer) + 1 deterministic stage (WaveScheduler) wired as a resumable DAG. Each stage writes a typed artifact to disk; SQLite caches stage outputs by input-hash; critics self-heal up to 3 attempts. Three new FastAPI endpoints: `/discover`, `/plan`, `/approve/backlog/{repo_id}`.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, SQLite (via existing `MigrationRepository` extension), `agent-framework` + `agent_framework_foundry`, `tree-sitter-languages` (new dep), `pytest` + `pytest-asyncio`.

**Conventions:**
- All paths in this plan are relative to `ms-agent-harness/` (the package root).
- Tests use the existing `tests/conftest.py` mock for `agent_framework` (so `@tool` is a passthrough).
- Mock LLM calls in integration tests by patching `agent_harness.base.create_agent` to return a stub whose `.run()` returns canned text. Follow the pattern used in existing `tests/test_integration.py`.
- Commit after every passing test step. Commit messages use Conventional Commits (`feat:`, `test:`, `chore:`, `fix:`).

---

## File Structure

**New package `agent_harness/discovery/`:**

| File | Responsibility |
|---|---|
| `__init__.py` | Public re-exports (`run_discovery`, `run_planning`). |
| `artifacts.py` | All Pydantic models for typed artifacts. One file — they reference each other. |
| `paths.py` | Single source of truth for artifact paths under `discovery/<repo_id>/...`. |
| `tools/__init__.py` | Re-exports tool functions. |
| `tools/tree_sitter_py.py` | Deterministic Python AST extraction (imports + boto3 call sites). |
| `tools/aws_sdk_patterns.py` | boto3/aioboto3 call → AWS resource kind+name resolver. |
| `tools/graph_io.py` | Build/serialize/load `DependencyGraph`. |
| `wave_scheduler.py` | Pure-Python topological-layering of stories → `BacklogItem` list. |
| `repo_scanner.py` | LLM agent: produces `Inventory`. |
| `dependency_grapher.py` | LLM agent (deterministic-first): produces `DependencyGraph`. |
| `brd_extractor.py` | LLM agent: produces per-module + system BRD markdown. |
| `architect.py` | LLM agent: produces per-module + system design markdown. |
| `story_decomposer.py` | LLM agent: produces `Stories` (epics + stories). |
| `critics/__init__.py` | Re-exports. |
| `critics/base.py` | Shared `CriticReport` runner. |
| `critics/graph_critic.py` | Validates `graph.json` against ground-truth scan. |
| `critics/brd_critic.py` | Validates BRD coverage. |
| `critics/design_critic.py` | Validates design coverage. |
| `critics/story_critic.py` | Validates story DAG and acceptance criteria. |
| `workflow.py` | Stage runner: hash → cache → 3-attempt self-heal loop → write artifact. |
| `prompts/repo_scanner.md` | System prompt. |
| `prompts/dependency_grapher.md` | System prompt. |
| `prompts/brd_extractor.md` | System prompt. |
| `prompts/architect.md` | System prompt. |
| `prompts/story_decomposer.md` | System prompt. |
| `prompts/critic_graph.md`, `critic_brd.md`, `critic_design.md`, `critic_story.md` | Critic system prompts. |

**Modified files:**
- `agent_harness/persistence/repository.py` — add `discovery_runs` and `discovery_stage_cache` tables and CRUD.
- `agent_harness/orchestrator/api.py` — add `/discover`, `/plan`, `/approve/backlog/{repo_id}`, `GET /discover/{repo_id}`.
- `agent_harness/config.py` — add new role defaults.
- `config/settings.yaml` — add new model routings.
- `requirements.txt` — add `tree-sitter-languages>=1.10.0` and `tree-sitter>=0.21.0`.
- `tests/conftest.py` — add fixtures for the synthetic 3-module repo (only if missing).

**New test files:**
- `tests/test_discovery_artifacts.py`
- `tests/test_tree_sitter_py.py`
- `tests/test_aws_sdk_patterns.py`
- `tests/test_graph_io.py`
- `tests/test_wave_scheduler.py`
- `tests/test_discovery_repository.py`
- `tests/test_repo_scanner.py`
- `tests/test_dependency_grapher.py`
- `tests/test_brd_extractor.py`
- `tests/test_architect.py`
- `tests/test_story_decomposer.py`
- `tests/test_discovery_workflow.py`
- `tests/test_discovery_api.py`
- `tests/test_discovery_e2e.py`
- `tests/fixtures/synthetic_repo/` — 3-module Python Lambda fixture (orders, payments, notifications).

---

## Task 1: Scaffolding — Pydantic artifacts and paths

**Files:**
- Create: `agent_harness/discovery/__init__.py`
- Create: `agent_harness/discovery/artifacts.py`
- Create: `agent_harness/discovery/paths.py`
- Test: `tests/test_discovery_artifacts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_artifacts.py
import json
from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, DependencyGraph, GraphNode, GraphEdge,
    ModuleBRD, SystemBRD, ModuleDesign, SystemDesign,
    Epic, Story, AcceptanceCriterion, Stories,
    BacklogItem, Backlog, CriticReport,
)


def test_inventory_round_trip():
    inv = Inventory(
        repo_meta={"root_path": "/r", "total_files": 3, "total_loc": 100,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="src/lambda/orders", language="python",
                         handler_entrypoint="src/lambda/orders/handler.py",
                         loc=42, config_files=["src/lambda/orders/requirements.txt"])
        ],
    )
    raw = inv.model_dump_json()
    again = Inventory.model_validate_json(raw)
    assert again == inv


def test_graph_round_trip():
    g = DependencyGraph(
        nodes=[GraphNode(id="orders", kind="module", attrs={}),
               GraphNode(id="orders-table", kind="aws_resource",
                         attrs={"resource_kind": "dynamodb_table"})],
        edges=[GraphEdge(src="orders", dst="orders-table", kind="reads")],
    )
    again = DependencyGraph.model_validate_json(g.model_dump_json())
    assert again == g


def test_backlog_item_is_superset_of_migrate_request():
    """BacklogItem must be JSON-compatible with the existing /migrate endpoint."""
    from agent_harness.orchestrator.api import MigrationRequest
    item = BacklogItem(
        module="orders", language="python", work_item_id="WI-1",
        title="Migrate orders", description="...", acceptance_criteria="...",
        wave=1,
    )
    payload = json.loads(item.model_dump_json())
    payload.pop("wave")
    MigrationRequest.model_validate(payload)  # must not raise


def test_critic_report_pass_fail():
    r = CriticReport(verdict="PASS", reasons=[], suggestions=[])
    assert r.verdict == "PASS"
    r2 = CriticReport(verdict="FAIL", reasons=["missing edge x→y"], suggestions=["add edge"])
    assert r2.verdict == "FAIL"
    assert "missing" in r2.reasons[0]


def test_story_dependencies():
    s = Story(id="S1", epic_id="E1", title="t", description="d",
              acceptance_criteria=[AcceptanceCriterion(text="a")],
              depends_on=["S0"], blocks=[], estimate="M")
    assert s.depends_on == ["S0"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_artifacts.py -v`
Expected: ImportError — module `agent_harness.discovery.artifacts` does not exist.

- [ ] **Step 3: Create `paths.py`**

```python
# agent_harness/discovery/paths.py
"""Single source of truth for discovery artifact paths."""
from pathlib import Path

DISCOVERY_ROOT = Path("discovery")


def repo_dir(repo_id: str) -> Path:
    return DISCOVERY_ROOT / repo_id


def inventory_path(repo_id: str) -> Path:
    return repo_dir(repo_id) / "inventory.json"


def graph_path(repo_id: str) -> Path:
    return repo_dir(repo_id) / "graph.json"


def brd_dir(repo_id: str) -> Path:
    return repo_dir(repo_id) / "brd"


def module_brd_path(repo_id: str, module_id: str) -> Path:
    return brd_dir(repo_id) / f"{module_id}.md"


def system_brd_path(repo_id: str) -> Path:
    return brd_dir(repo_id) / "_system.md"


def design_dir(repo_id: str) -> Path:
    return repo_dir(repo_id) / "design"


def module_design_path(repo_id: str, module_id: str) -> Path:
    return design_dir(repo_id) / f"{module_id}.md"


def system_design_path(repo_id: str) -> Path:
    return design_dir(repo_id) / "_system.md"


def stories_path(repo_id: str) -> Path:
    return repo_dir(repo_id) / "stories.json"


def backlog_path(repo_id: str) -> Path:
    return repo_dir(repo_id) / "backlog.json"


def blocked_path(repo_id: str, stage: str) -> Path:
    return repo_dir(repo_id) / stage / "blocked.md"
```

- [ ] **Step 4: Create `artifacts.py`**

```python
# agent_harness/discovery/artifacts.py
"""Pydantic models for every discovery artifact."""
from typing import Literal
from pydantic import BaseModel, Field

ResourceKind = Literal[
    "dynamodb_table", "s3_bucket", "sqs_queue", "sns_topic",
    "kinesis_stream", "secrets_manager_secret", "lambda_function",
]
EdgeKind = Literal[
    "imports", "reads", "writes", "produces", "consumes",
    "invokes", "shares_db",
]
NodeKind = Literal["module", "aws_resource"]


class RepoMeta(BaseModel):
    root_path: str
    total_files: int
    total_loc: int
    discovered_at: str  # ISO-8601 UTC


class ModuleRecord(BaseModel):
    id: str
    path: str
    language: str
    handler_entrypoint: str
    loc: int
    config_files: list[str] = Field(default_factory=list)


class Inventory(BaseModel):
    repo_meta: RepoMeta | dict
    modules: list[ModuleRecord]


class GraphNode(BaseModel):
    id: str
    kind: NodeKind
    attrs: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    src: str
    dst: str
    kind: EdgeKind


class DependencyGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class ModuleBRD(BaseModel):
    """Free-form markdown body, but we wrap it for round-trip."""
    module_id: str
    body: str  # markdown


class SystemBRD(BaseModel):
    body: str  # markdown


class ModuleDesign(BaseModel):
    module_id: str
    body: str


class SystemDesign(BaseModel):
    body: str


class AcceptanceCriterion(BaseModel):
    text: str


class Story(BaseModel):
    id: str
    epic_id: str
    title: str
    description: str
    acceptance_criteria: list[AcceptanceCriterion]
    depends_on: list[str] = Field(default_factory=list)
    blocks: list[str] = Field(default_factory=list)
    estimate: Literal["S", "M", "L"] = "M"


class Epic(BaseModel):
    id: str
    module_id: str
    title: str
    story_ids: list[str] = Field(default_factory=list)


class Stories(BaseModel):
    epics: list[Epic]
    stories: list[Story]


class BacklogItem(BaseModel):
    """Strict superset of MigrationRequest in orchestrator/api.py.

    Drop the `wave` field and the rest must validate as MigrationRequest.
    """
    module: str
    language: str
    work_item_id: str = "LOCAL"
    title: str = ""
    description: str = ""
    acceptance_criteria: str = ""
    wave: int


class Backlog(BaseModel):
    items: list[BacklogItem]


class CriticReport(BaseModel):
    verdict: Literal["PASS", "FAIL"]
    reasons: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: Create `__init__.py`**

```python
# agent_harness/discovery/__init__.py
"""Discovery & Planning subpackage."""
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_discovery_artifacts.py -v`
Expected: 5 PASS.

- [ ] **Step 7: Commit**

```bash
git add agent_harness/discovery/__init__.py agent_harness/discovery/artifacts.py \
        agent_harness/discovery/paths.py tests/test_discovery_artifacts.py
git commit -m "feat(discovery): scaffold subpackage with Pydantic artifacts and paths"
```

---

## Task 2: SQLite tables — `discovery_runs` and `discovery_stage_cache`

**Files:**
- Modify: `agent_harness/persistence/repository.py` (add new tables and methods)
- Test: `tests/test_discovery_repository.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_repository.py
import pytest
from agent_harness.persistence.repository import MigrationRepository


@pytest.fixture
def repo(tmp_path):
    r = MigrationRepository(db_path=tmp_path / "test.db")
    r.initialize()
    return r


def test_create_discovery_run(repo):
    repo.create_discovery_run("my-repo")
    run = repo.get_discovery_run("my-repo")
    assert run["repo_id"] == "my-repo"
    assert run["approved"] == 0


def test_stage_cache_hit_miss(repo):
    repo.create_discovery_run("my-repo")
    assert repo.stage_cache_hit("my-repo", "scanner", "h1") is False
    repo.cache_stage("my-repo", "scanner", "h1", "discovery/my-repo/inventory.json")
    assert repo.stage_cache_hit("my-repo", "scanner", "h1") is True
    assert repo.stage_cache_hit("my-repo", "scanner", "different-hash") is False


def test_stage_cache_overwrites_on_new_hash(repo):
    repo.create_discovery_run("my-repo")
    repo.cache_stage("my-repo", "scanner", "h1", "p1")
    repo.cache_stage("my-repo", "scanner", "h2", "p2")
    assert repo.stage_cache_hit("my-repo", "scanner", "h1") is False
    assert repo.stage_cache_hit("my-repo", "scanner", "h2") is True


def test_approve_backlog(repo):
    repo.create_discovery_run("my-repo")
    repo.approve_backlog("my-repo", approver="alice", comment="lgtm")
    run = repo.get_discovery_run("my-repo")
    assert run["approved"] == 1
    assert run["approver"] == "alice"
    assert run["approval_comment"] == "lgtm"
    assert run["approved_at"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_repository.py -v`
Expected: AttributeError — `MigrationRepository` has no method `create_discovery_run`.

- [ ] **Step 3: Extend repository**

In `agent_harness/persistence/repository.py`, append to the `executescript` block (inside `initialize`):

```python
                CREATE TABLE IF NOT EXISTS discovery_runs (
                    repo_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved INTEGER DEFAULT 0,
                    approver TEXT,
                    approval_comment TEXT,
                    approved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS discovery_stage_cache (
                    repo_id TEXT NOT NULL,
                    stage_name TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (repo_id, stage_name)
                );
```

Then add these methods at the end of the class (before `_now`):

```python
    # ─── Discovery Runs ────────────────────────────────────────────────

    def create_discovery_run(self, repo_id: str):
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO discovery_runs
                   (repo_id, created_at, updated_at, approved)
                   VALUES (?, ?, ?, 0)""",
                (repo_id, _now(), _now()),
            )

    def get_discovery_run(self, repo_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM discovery_runs WHERE repo_id = ?", (repo_id,)
            ).fetchone()
            return dict(row) if row else None

    def approve_backlog(self, repo_id: str, approver: str, comment: str = ""):
        with self._connect() as conn:
            conn.execute(
                """UPDATE discovery_runs
                   SET approved = 1, approver = ?, approval_comment = ?,
                       approved_at = ?, updated_at = ?
                   WHERE repo_id = ?""",
                (approver, comment, _now(), _now(), repo_id),
            )

    def is_backlog_approved(self, repo_id: str) -> bool:
        run = self.get_discovery_run(repo_id)
        return bool(run and run["approved"])

    # ─── Discovery Stage Cache ─────────────────────────────────────────

    def stage_cache_hit(self, repo_id: str, stage_name: str, input_hash: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT input_hash FROM discovery_stage_cache
                   WHERE repo_id = ? AND stage_name = ?""",
                (repo_id, stage_name),
            ).fetchone()
            return bool(row) and row["input_hash"] == input_hash

    def cache_stage(self, repo_id: str, stage_name: str, input_hash: str, artifact_path: str):
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO discovery_stage_cache
                   (repo_id, stage_name, input_hash, artifact_path, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (repo_id, stage_name, input_hash, artifact_path, _now()),
            )

    def get_cached_stage_path(self, repo_id: str, stage_name: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT artifact_path FROM discovery_stage_cache
                   WHERE repo_id = ? AND stage_name = ?""",
                (repo_id, stage_name),
            ).fetchone()
            return row["artifact_path"] if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_discovery_repository.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Run full test suite to verify no regression**

Run: `pytest tests/test_repository.py -v`
Expected: existing repository tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_harness/persistence/repository.py tests/test_discovery_repository.py
git commit -m "feat(persistence): add discovery_runs and discovery_stage_cache tables"
```

---

## Task 3: Tools — `tree_sitter_py`

**Files:**
- Create: `agent_harness/discovery/tools/__init__.py`
- Create: `agent_harness/discovery/tools/tree_sitter_py.py`
- Modify: `requirements.txt`
- Test: `tests/test_tree_sitter_py.py`

- [ ] **Step 1: Add deps**

Append to `requirements.txt`:

```
# ── Discovery layer ──
tree-sitter>=0.21.0
tree-sitter-languages>=1.10.0
```

Install: `pip install tree-sitter tree-sitter-languages`

- [ ] **Step 2: Write the failing test**

```python
# tests/test_tree_sitter_py.py
from agent_harness.discovery.tools.tree_sitter_py import (
    parse_imports, extract_boto3_calls,
)


def test_parse_imports_simple(tmp_path):
    f = tmp_path / "m.py"
    f.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "from .siblings import helper\n"
        "from ..pkg.mod import x as y\n"
    )
    imports = parse_imports(str(f))
    assert {"os", "pathlib", ".siblings", "..pkg.mod"} == {i.module for i in imports}


def test_extract_boto3_calls(tmp_path):
    f = tmp_path / "h.py"
    f.write_text(
        "import boto3\n"
        "ddb = boto3.resource('dynamodb')\n"
        "table = ddb.Table('Orders')\n"
        "table.put_item(Item={'id': '1'})\n"
        "s3 = boto3.client('s3')\n"
        "s3.get_object(Bucket='my-bucket', Key='k')\n"
    )
    calls = extract_boto3_calls(str(f))
    services = {c.service for c in calls}
    assert "dynamodb" in services
    assert "s3" in services
    methods = {c.method for c in calls}
    assert "put_item" in methods
    assert "get_object" in methods


def test_extract_boto3_resource_names(tmp_path):
    f = tmp_path / "h.py"
    f.write_text(
        "import boto3\n"
        "t = boto3.resource('dynamodb').Table('Orders')\n"
        "boto3.client('s3').put_object(Bucket='analytics-bucket', Key='k', Body='b')\n"
    )
    calls = extract_boto3_calls(str(f))
    # We should be able to read at least one literal resource name from kwargs.
    seen = {c.resource_name for c in calls if c.resource_name}
    assert "Orders" in seen or "analytics-bucket" in seen
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_tree_sitter_py.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `tools/__init__.py`**

```python
# agent_harness/discovery/tools/__init__.py
"""Deterministic tools used by discovery agents."""
```

- [ ] **Step 5: Implement `tree_sitter_py.py`**

```python
# agent_harness/discovery/tools/tree_sitter_py.py
"""Deterministic Python source extraction.

Uses the stdlib `ast` module — tree-sitter is reserved for the v1.1 cross-language
adapter layer. Naming the module tree_sitter_py keeps the call sites stable when
we swap implementations.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Import:
    module: str
    file: str
    line: int


@dataclass
class Boto3Call:
    service: str            # 'dynamodb', 's3', ...
    method: str             # 'put_item', 'get_object', ...
    resource_name: str | None  # literal table/bucket/queue name when extractable
    file: str
    line: int


def parse_imports(path: str) -> list[Import]:
    """Return every import statement in the file.

    `from .a.b import x` → module = '.a.b'; `from ..p import y` → '..p'.
    """
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, filename=path)
    out: list[Import] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append(Import(module=alias.name, file=path, line=node.lineno))
        elif isinstance(node, ast.ImportFrom):
            level = "." * (node.level or 0)
            mod = (node.module or "")
            out.append(Import(module=f"{level}{mod}", file=path, line=node.lineno))
    return out


_BOTO3_FACTORIES = {"client", "resource"}
# Resource-creation kwargs we know carry a resource name literal:
_NAME_KWARGS = {
    "TableName": "dynamodb",   # ddb.Table(... TableName=...)
    "Bucket": "s3",
    "QueueUrl": "sqs",
    "TopicArn": "sns",
    "StreamName": "kinesis",
    "SecretId": "secretsmanager",
    "FunctionName": "lambda",
}


def extract_boto3_calls(path: str) -> list[Boto3Call]:
    """Find every boto3/aioboto3 call site and return service+method+name."""
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src, filename=path)

    # First pass: collect aliases bound to boto3.client(svc) or boto3.resource(svc).
    service_of: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
           isinstance(node.targets[0], ast.Name):
            svc = _service_from_factory(node.value)
            if svc:
                service_of[node.targets[0].id] = svc
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            svc = _service_from_factory(node.value)
            if svc:
                service_of[node.target.id] = svc

    calls: list[Boto3Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # client.method(...) / resource.method(...)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            svc = service_of.get(node.func.value.id)
            if svc:
                calls.append(Boto3Call(
                    service=svc,
                    method=node.func.attr,
                    resource_name=_extract_resource_name(node),
                    file=path,
                    line=node.lineno,
                ))
                continue
        # Inline form: boto3.client('s3').put_object(...) or
        #             boto3.resource('dynamodb').Table('Orders').put_item(...)
        svc = _service_from_chained_call(node)
        if svc:
            calls.append(Boto3Call(
                service=svc,
                method=node.func.attr if isinstance(node.func, ast.Attribute) else "<call>",
                resource_name=_extract_resource_name(node),
                file=path,
                line=node.lineno,
            ))
    return calls


def _service_from_factory(value: ast.AST | None) -> str | None:
    """Return the service string from `boto3.client('s3')` / `boto3.resource('s3')`."""
    if not isinstance(value, ast.Call):
        return None
    func = value.func
    if isinstance(func, ast.Attribute) and func.attr in _BOTO3_FACTORIES \
       and isinstance(func.value, ast.Name) and func.value.id in {"boto3", "aioboto3"}:
        if value.args and isinstance(value.args[0], ast.Constant) \
           and isinstance(value.args[0].value, str):
            return value.args[0].value
    return None


def _service_from_chained_call(call: ast.Call) -> str | None:
    """Walk down a call chain to find the inner boto3 factory."""
    cur: ast.AST = call.func
    while isinstance(cur, ast.Attribute):
        cur = cur.value
        if isinstance(cur, ast.Call):
            svc = _service_from_factory(cur)
            if svc:
                return svc
    return None


def _extract_resource_name(call: ast.Call) -> str | None:
    """Look at first positional arg or known kwargs for a literal resource name."""
    if call.args and isinstance(call.args[0], ast.Constant) \
       and isinstance(call.args[0].value, str):
        return call.args[0].value
    for kw in call.keywords:
        if kw.arg in _NAME_KWARGS and isinstance(kw.value, ast.Constant) \
           and isinstance(kw.value.value, str):
            return kw.value.value
    return None
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_tree_sitter_py.py -v`
Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt agent_harness/discovery/tools/__init__.py \
        agent_harness/discovery/tools/tree_sitter_py.py tests/test_tree_sitter_py.py
git commit -m "feat(discovery): add Python AST tool for imports and boto3 calls"
```

---

## Task 4: Tools — `aws_sdk_patterns`

**Files:**
- Create: `agent_harness/discovery/tools/aws_sdk_patterns.py`
- Test: `tests/test_aws_sdk_patterns.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aws_sdk_patterns.py
from agent_harness.discovery.tools.aws_sdk_patterns import resolve, ResourceRef
from agent_harness.discovery.tools.tree_sitter_py import Boto3Call


def call(service, method, name=None, line=1):
    return Boto3Call(service=service, method=method, resource_name=name,
                     file="x.py", line=line)


def test_dynamodb_put_is_write():
    ref = resolve(call("dynamodb", "put_item", "Orders"))
    assert ref == ResourceRef(kind="dynamodb_table", name="Orders", access="writes")


def test_dynamodb_get_is_read():
    ref = resolve(call("dynamodb", "get_item", "Orders"))
    assert ref.access == "reads"


def test_s3_put_object_is_write():
    ref = resolve(call("s3", "put_object", "my-bucket"))
    assert ref == ResourceRef(kind="s3_bucket", name="my-bucket", access="writes")


def test_s3_get_object_is_read():
    ref = resolve(call("s3", "get_object", "my-bucket"))
    assert ref.access == "reads"


def test_sqs_send_message_is_produces():
    ref = resolve(call("sqs", "send_message", "my-queue"))
    assert ref == ResourceRef(kind="sqs_queue", name="my-queue", access="produces")


def test_sns_publish_is_produces():
    ref = resolve(call("sns", "publish", "topic-arn"))
    assert ref == ResourceRef(kind="sns_topic", name="topic-arn", access="produces")


def test_kinesis_put_record_is_produces():
    ref = resolve(call("kinesis", "put_record", "stream-1"))
    assert ref.kind == "kinesis_stream"
    assert ref.access == "produces"


def test_secrets_manager_is_read():
    ref = resolve(call("secretsmanager", "get_secret_value", "db/password"))
    assert ref == ResourceRef(kind="secrets_manager_secret", name="db/password", access="reads")


def test_lambda_invoke_is_invokes():
    ref = resolve(call("lambda", "invoke", "other-fn"))
    assert ref == ResourceRef(kind="lambda_function", name="other-fn", access="invokes")


def test_unknown_returns_none():
    assert resolve(call("comprehend", "detect_sentiment")) is None


def test_no_resource_name_returns_ref_without_name():
    ref = resolve(call("s3", "list_buckets"))
    # list_buckets is metadata-only — we treat as read with name = None.
    assert ref is not None and ref.access == "reads" and ref.name is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_aws_sdk_patterns.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# agent_harness/discovery/tools/aws_sdk_patterns.py
"""boto3 call pattern → typed AWS resource reference.

Catalog-driven; ambiguous calls (dynamic resource names, unknown methods) return
None and are flagged for LLM disambiguation in the DependencyGrapher.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from .tree_sitter_py import Boto3Call

Access = Literal["reads", "writes", "produces", "consumes", "invokes"]
ResourceKind = Literal[
    "dynamodb_table", "s3_bucket", "sqs_queue", "sns_topic",
    "kinesis_stream", "secrets_manager_secret", "lambda_function",
]


@dataclass(frozen=True)
class ResourceRef:
    kind: ResourceKind
    name: str | None
    access: Access


# Per-service rules. Methods not listed default per the service's "default_access".
# An empty default_access means we cannot infer anything → return None.
_RULES: dict[str, dict] = {
    "dynamodb": {
        "kind": "dynamodb_table",
        "writes": {"put_item", "update_item", "delete_item", "batch_write_item",
                   "transact_write_items"},
        "reads": {"get_item", "query", "scan", "batch_get_item",
                  "transact_get_items", "describe_table"},
        "default_access": "reads",
    },
    "s3": {
        "kind": "s3_bucket",
        "writes": {"put_object", "delete_object", "copy_object",
                   "complete_multipart_upload", "upload_file", "upload_fileobj"},
        "reads": {"get_object", "head_object", "list_objects", "list_objects_v2",
                  "list_buckets", "head_bucket", "download_file", "download_fileobj"},
        "default_access": "reads",
    },
    "sqs": {
        "kind": "sqs_queue",
        "produces": {"send_message", "send_message_batch"},
        "consumes": {"receive_message", "delete_message", "delete_message_batch",
                     "change_message_visibility"},
        "default_access": None,
    },
    "sns": {
        "kind": "sns_topic",
        "produces": {"publish", "publish_batch"},
        "default_access": None,
    },
    "kinesis": {
        "kind": "kinesis_stream",
        "produces": {"put_record", "put_records"},
        "consumes": {"get_records", "get_shard_iterator"},
        "default_access": None,
    },
    "secretsmanager": {
        "kind": "secrets_manager_secret",
        "reads": {"get_secret_value", "describe_secret"},
        "writes": {"put_secret_value", "update_secret"},
        "default_access": None,
    },
    "lambda": {
        "kind": "lambda_function",
        "invokes": {"invoke", "invoke_async"},
        "default_access": None,
    },
}


def resolve(c: Boto3Call) -> ResourceRef | None:
    rule = _RULES.get(c.service)
    if not rule:
        return None
    kind: ResourceKind = rule["kind"]
    for access in ("reads", "writes", "produces", "consumes", "invokes"):
        if c.method in rule.get(access, set()):
            return ResourceRef(kind=kind, name=c.resource_name, access=access)
    default = rule["default_access"]
    if default is None:
        return None
    return ResourceRef(kind=kind, name=c.resource_name, access=default)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_aws_sdk_patterns.py -v`
Expected: 11 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/discovery/tools/aws_sdk_patterns.py tests/test_aws_sdk_patterns.py
git commit -m "feat(discovery): map boto3 call patterns to typed AWS resource refs"
```

---

## Task 5: Tools — `graph_io`

**Files:**
- Create: `agent_harness/discovery/tools/graph_io.py`
- Test: `tests/test_graph_io.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph_io.py
import json
from pathlib import Path
from agent_harness.discovery.artifacts import DependencyGraph
from agent_harness.discovery.tools.graph_io import GraphBuilder, save, load


def test_builder_dedupes_nodes_and_edges():
    b = GraphBuilder()
    b.add_module("orders")
    b.add_module("orders")  # duplicate
    b.add_resource("dynamodb_table", "Orders")
    b.add_resource("dynamodb_table", "Orders")  # duplicate
    b.add_edge("orders", "dynamodb_table:Orders", "writes")
    b.add_edge("orders", "dynamodb_table:Orders", "writes")  # duplicate
    g = b.build()
    assert len(g.nodes) == 2
    assert len(g.edges) == 1


def test_resource_id_includes_kind():
    b = GraphBuilder()
    b.add_resource("s3_bucket", "logs")
    g = b.build()
    assert g.nodes[0].id == "s3_bucket:logs"
    assert g.nodes[0].attrs["resource_kind"] == "s3_bucket"


def test_resource_without_name_uses_unknown(tmp_path):
    b = GraphBuilder()
    b.add_resource("s3_bucket", None)
    g = b.build()
    assert g.nodes[0].id.startswith("s3_bucket:<unknown:")


def test_save_and_load_round_trip(tmp_path):
    b = GraphBuilder()
    b.add_module("a")
    b.add_module("b")
    b.add_edge("a", "b", "imports")
    g = b.build()
    p = tmp_path / "g.json"
    save(g, p)
    again = load(p)
    assert again == g
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_graph_io.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# agent_harness/discovery/tools/graph_io.py
"""Build, serialize, and load a DependencyGraph."""
from __future__ import annotations

import uuid
from pathlib import Path

from ..artifacts import DependencyGraph, GraphEdge, GraphNode


class GraphBuilder:
    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: set[tuple[str, str, str]] = set()

    def add_module(self, module_id: str, attrs: dict | None = None) -> str:
        if module_id not in self._nodes:
            self._nodes[module_id] = GraphNode(
                id=module_id, kind="module", attrs=attrs or {},
            )
        return module_id

    def add_resource(self, kind: str, name: str | None, attrs: dict | None = None) -> str:
        node_id = f"{kind}:{name}" if name else f"{kind}:<unknown:{uuid.uuid4().hex[:8]}>"
        if node_id not in self._nodes:
            merged = {"resource_kind": kind, **(attrs or {})}
            if name:
                merged["resource_name"] = name
            self._nodes[node_id] = GraphNode(id=node_id, kind="aws_resource", attrs=merged)
        return node_id

    def add_edge(self, src: str, dst: str, kind: str) -> None:
        self._edges.add((src, dst, kind))

    def build(self) -> DependencyGraph:
        return DependencyGraph(
            nodes=list(self._nodes.values()),
            edges=[GraphEdge(src=s, dst=d, kind=k) for (s, d, k) in sorted(self._edges)],
        )


def save(graph: DependencyGraph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(graph.model_dump_json(indent=2), encoding="utf-8")


def load(path: Path) -> DependencyGraph:
    return DependencyGraph.model_validate_json(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_graph_io.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/discovery/tools/graph_io.py tests/test_graph_io.py
git commit -m "feat(discovery): GraphBuilder for deduped node/edge construction + IO"
```

---

## Task 6: WaveScheduler (deterministic, no LLM)

**Files:**
- Create: `agent_harness/discovery/wave_scheduler.py`
- Test: `tests/test_wave_scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wave_scheduler.py
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
    waves = {item.module: item.wave for item in backlog.items}
    assert {item.wave for item in backlog.items} == {1, 2, 3}


def test_independent_stories_share_first_wave():
    s = _stories([_story("A"), _story("B"), _story("C", ["A"])])
    backlog = schedule(s, language_by_module={"orders": "python"})
    waves = {item.module + ":" + str(i): item.wave for i, item in enumerate(backlog.items)}
    # A and B are wave 1; C is wave 2.
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wave_scheduler.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# agent_harness/discovery/wave_scheduler.py
"""Deterministic topological layering of stories into migration waves.

No LLM. Cycle = hard error naming the cycle members.
"""
from __future__ import annotations

from collections import defaultdict, deque

from .artifacts import Backlog, BacklogItem, Stories


class CycleError(ValueError):
    pass


def schedule(stories: Stories, language_by_module: dict[str, str]) -> Backlog:
    by_id = {s.id: s for s in stories.stories}

    # Validate referenced ids exist.
    for s in stories.stories:
        for dep in s.depends_on:
            if dep not in by_id:
                raise ValueError(f"Story {s.id} depends_on unknown story id: {dep}")

    # Kahn's algorithm with layering.
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
            wave=layer_of[sid],
        ))
    return Backlog(items=items)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_wave_scheduler.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/discovery/wave_scheduler.py tests/test_wave_scheduler.py
git commit -m "feat(discovery): deterministic wave scheduler with cycle detection"
```

---

## Task 7: Synthetic 3-module fixture repo

**Files:**
- Create: `tests/fixtures/synthetic_repo/orders/handler.py`
- Create: `tests/fixtures/synthetic_repo/orders/requirements.txt`
- Create: `tests/fixtures/synthetic_repo/payments/handler.py`
- Create: `tests/fixtures/synthetic_repo/payments/requirements.txt`
- Create: `tests/fixtures/synthetic_repo/notifications/handler.py`
- Create: `tests/fixtures/synthetic_repo/notifications/requirements.txt`
- Create: `tests/fixtures/synthetic_repo/shared/__init__.py`
- Create: `tests/fixtures/synthetic_repo/shared/util.py`

This fixture is the integration-test ground truth. Hand-author the dep structure so we can assert exact edges in Task 12+.

- [ ] **Step 1: Create `orders/handler.py`**

```python
# tests/fixtures/synthetic_repo/orders/handler.py
"""Orders Lambda — receives HTTP, writes to DynamoDB, fans out to SQS."""
import json
import boto3
from shared.util import normalize

ddb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")
table = ddb.Table("Orders")


def handler(event, context):
    body = json.loads(event["body"])
    item = normalize(body)
    table.put_item(Item=item)
    sqs.send_message(QueueUrl="payments-queue", MessageBody=json.dumps(item))
    return {"statusCode": 200, "body": json.dumps({"id": item["id"]})}
```

- [ ] **Step 2: Create `orders/requirements.txt`**

```
boto3>=1.34.0
```

- [ ] **Step 3: Create `payments/handler.py`**

```python
# tests/fixtures/synthetic_repo/payments/handler.py
"""Payments Lambda — consumes SQS, reads Orders, writes Payments table, publishes SNS."""
import json
import boto3
from shared.util import normalize

ddb = boto3.resource("dynamodb")
orders = ddb.Table("Orders")
payments = ddb.Table("Payments")
sns = boto3.client("sns")


def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        order = orders.get_item(Key={"id": body["id"]}).get("Item")
        result = normalize({"order_id": body["id"], "status": "paid"})
        payments.put_item(Item=result)
        sns.publish(TopicArn="payment-events", Message=json.dumps(result))
    return {"statusCode": 200}
```

- [ ] **Step 4: Create `payments/requirements.txt`**

```
boto3>=1.34.0
```

- [ ] **Step 5: Create `notifications/handler.py`**

```python
# tests/fixtures/synthetic_repo/notifications/handler.py
"""Notifications Lambda — consumes SNS, reads Secrets Manager, posts to webhook."""
import json
import boto3

sm = boto3.client("secretsmanager")


def handler(event, context):
    secret = sm.get_secret_value(SecretId="webhook/url")
    for record in event["Records"]:
        msg = record["Sns"]["Message"]
        # Pretend to send notification.
        print(f"notify {secret['SecretString']}: {msg}")
    return {"statusCode": 200}
```

- [ ] **Step 6: Create `notifications/requirements.txt`**

```
boto3>=1.34.0
```

- [ ] **Step 7: Create `shared/__init__.py`**

```python
```

- [ ] **Step 8: Create `shared/util.py`**

```python
# tests/fixtures/synthetic_repo/shared/util.py
"""Shared helpers used by orders and payments."""
import uuid


def normalize(d: dict) -> dict:
    out = dict(d)
    out.setdefault("id", uuid.uuid4().hex)
    return out
```

- [ ] **Step 9: Commit**

```bash
git add tests/fixtures/synthetic_repo/
git commit -m "test(discovery): synthetic 3-module Lambda fixture repo"
```

---

## Task 8: RepoScanner agent + sanity check

**Files:**
- Create: `agent_harness/discovery/repo_scanner.py`
- Create: `agent_harness/discovery/prompts/repo_scanner.md`
- Modify: `agent_harness/config.py` (add new role defaults — already supported via fallback, but note in `models` dict)
- Modify: `config/settings.yaml`
- Test: `tests/test_repo_scanner.py`

- [ ] **Step 1: Update `config/settings.yaml`**

Append under `models:`:

```yaml
  # ── Discovery layer ──
  repo_scanner: gpt-4o-mini
  dependency_grapher: gpt-4o-mini
  brd_extractor: gpt-4o
  architect: gpt-4o
  story_decomposer: gpt-4o
  wave_scheduler: gpt-4o-mini   # unused; deterministic
  critic_graph: gpt-4o-mini
  critic_brd: gpt-4o-mini
  critic_design: gpt-4o-mini
  critic_story: gpt-4o-mini
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_repo_scanner.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.repo_scanner import scan_repo, sanity_check
from agent_harness.discovery.artifacts import Inventory, ModuleRecord
from agent_harness.discovery import paths

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


@pytest.mark.asyncio
async def test_scan_repo_writes_inventory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    canned = Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 8,
                   "total_loc": 60,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py",
                         loc=14, config_files=["orders/requirements.txt"]),
            ModuleRecord(id="payments", path="payments", language="python",
                         handler_entrypoint="payments/handler.py",
                         loc=18, config_files=["payments/requirements.txt"]),
            ModuleRecord(id="notifications", path="notifications", language="python",
                         handler_entrypoint="notifications/handler.py",
                         loc=12, config_files=["notifications/requirements.txt"]),
        ],
    ).model_dump_json()

    fake_agent = AsyncMock()
    fake_agent.run_with_retry = AsyncMock(return_value=canned)

    with patch("agent_harness.discovery.repo_scanner._run_agent",
               new=AsyncMock(return_value=canned)):
        out = await scan_repo(repo_id="synth", repo_path=str(FIXTURE))

    inv_path = paths.inventory_path("synth")
    assert inv_path.exists()
    inv = Inventory.model_validate_json(inv_path.read_text())
    assert {m.id for m in inv.modules} == {"orders", "payments", "notifications"}
    assert out == inv


def test_sanity_check_passes_on_valid_inventory():
    inv = Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py",
                         loc=10, config_files=[]),
        ],
    )
    report = sanity_check(inv, repo_root=FIXTURE)
    assert report.verdict == "PASS"


def test_sanity_check_fails_on_missing_handler():
    inv = Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="ghost", path="ghost", language="python",
                         handler_entrypoint="ghost/missing.py",
                         loc=10, config_files=[]),
        ],
    )
    report = sanity_check(inv, repo_root=FIXTURE)
    assert report.verdict == "FAIL"
    assert "ghost/missing.py" in report.reasons[0]


def test_sanity_check_fails_on_extension_mismatch():
    inv = Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="java",
                         handler_entrypoint="orders/handler.py",
                         loc=10, config_files=[]),
        ],
    )
    report = sanity_check(inv, repo_root=FIXTURE)
    assert report.verdict == "FAIL"
    assert any("language" in r for r in report.reasons)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_repo_scanner.py -v`
Expected: ImportError.

- [ ] **Step 4: Create `prompts/repo_scanner.md`**

```markdown
# Repo Scanner

You inventory a multi-module Python AWS Lambda repository.

## Inputs
You receive:
- `repo_path`: filesystem path to the repo root.
- A pre-listed file tree (top 200 entries).

## Output
Return ONLY a single JSON object matching this schema (no prose, no fences):

```
{
  "repo_meta": {
    "root_path": "<repo_path>",
    "total_files": <int>,
    "total_loc": <int>,
    "discovered_at": "<ISO-8601 UTC>"
  },
  "modules": [
    {
      "id": "<short slug>",
      "path": "<dir relative to repo root>",
      "language": "python",
      "handler_entrypoint": "<file path relative to repo root>",
      "loc": <int>,
      "config_files": ["<requirements.txt|template.yaml|...>"]
    }
  ]
}
```

## Rules
- Only include directories that look like deployable Lambda modules: a single
  Python file with a `handler(event, context)` function or one declared in a
  template/serverless config.
- `id` must be unique. Prefer the directory's basename, slugified.
- Use `read_file`, `list_directory`, `search_files` if you need to inspect
  individual files. Do not modify anything.
- If you cannot find a `handler` function, OMIT the module — do not guess.
- Skip `tests/`, `node_modules/`, `.git/`, `__pycache__/`, hidden dirs.
```

- [ ] **Step 5: Implement `repo_scanner.py`**

```python
# agent_harness/discovery/repo_scanner.py
"""RepoScanner — LLM agent that produces an Inventory."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import CriticReport, Inventory
from . import paths

logger = logging.getLogger("discovery.scanner")

_TREE_LIMIT = 200


def _list_tree(root: Path) -> list[str]:
    out = []
    for p in sorted(root.rglob("*")):
        if any(seg in {".git", "__pycache__", "node_modules", ".venv"}
               for seg in p.parts):
            continue
        out.append(str(p.relative_to(root)))
        if len(out) >= _TREE_LIMIT:
            break
    return out


async def _run_agent(message: str) -> str:
    """Indirection point so tests can patch a single seam."""
    agent = create_agent(role="repo_scanner",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def scan_repo(repo_id: str, repo_path: str,
                    extra_instructions: str = "") -> Inventory:
    root = Path(repo_path).resolve()
    listing = "\n".join(_list_tree(root))
    now = datetime.now(timezone.utc).isoformat()
    msg = (
        f"repo_path: {root}\n"
        f"discovered_at: {now}\n\n"
        f"## File tree (truncated to {_TREE_LIMIT} entries)\n{listing}\n\n"
        f"{extra_instructions}\n\n"
        f"Return ONLY the JSON object."
    )
    raw = await _run_agent(msg)
    inv = Inventory.model_validate_json(_strip_fences(raw))

    out_path = paths.inventory_path(repo_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(inv.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Wrote inventory to %s (%d modules)", out_path, len(inv.modules))
    return inv


def sanity_check(inv: Inventory, repo_root: Path) -> CriticReport:
    """Deterministic post-check — no LLM. Used in lieu of a critic for scanner."""
    reasons: list[str] = []
    for m in inv.modules:
        handler = (repo_root / m.handler_entrypoint)
        if not handler.is_file():
            reasons.append(f"handler not found: {m.handler_entrypoint}")
            continue
        ext = handler.suffix.lower()
        ext_to_lang = {".py": "python", ".js": "node", ".ts": "node",
                       ".java": "java", ".cs": "csharp"}
        expected = ext_to_lang.get(ext)
        if expected and m.language != expected:
            reasons.append(
                f"module {m.id}: language={m.language} but extension implies {expected}"
            )
    return CriticReport(
        verdict="PASS" if not reasons else "FAIL",
        reasons=reasons,
        suggestions=[],
    )


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_repo_scanner.py -v`
Expected: 4 PASS.

- [ ] **Step 7: Commit**

```bash
git add agent_harness/discovery/repo_scanner.py \
        agent_harness/discovery/prompts/repo_scanner.md \
        config/settings.yaml tests/test_repo_scanner.py
git commit -m "feat(discovery): RepoScanner agent + deterministic sanity check"
```

---

## Task 9: DependencyGrapher + graph_critic

**Files:**
- Create: `agent_harness/discovery/dependency_grapher.py`
- Create: `agent_harness/discovery/critics/__init__.py`
- Create: `agent_harness/discovery/critics/base.py`
- Create: `agent_harness/discovery/critics/graph_critic.py`
- Create: `agent_harness/discovery/prompts/dependency_grapher.md`
- Create: `agent_harness/discovery/prompts/critic_graph.md`
- Test: `tests/test_dependency_grapher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dependency_grapher.py
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from agent_harness.discovery.artifacts import Inventory, ModuleRecord
from agent_harness.discovery.dependency_grapher import build_graph
from agent_harness.discovery.critics.graph_critic import critique_graph
from agent_harness.discovery import paths

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


def _inv() -> Inventory:
    return Inventory(
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
    )


@pytest.mark.asyncio
async def test_build_graph_deterministic_path(tmp_path, monkeypatch):
    """When all calls resolve via aws_sdk_patterns, no LLM is invoked."""
    monkeypatch.chdir(tmp_path)
    with patch("agent_harness.discovery.dependency_grapher._run_agent",
               new=AsyncMock(return_value="{}")) as fake:
        g = await build_graph(repo_id="synth", repo_root=FIXTURE, inventory=_inv())
    fake.assert_not_called()  # synthetic repo is fully resolvable

    edges = {(e.src, e.dst, e.kind) for e in g.edges}
    # orders writes Orders table and produces to payments-queue
    assert ("orders", "dynamodb_table:Orders", "writes") in edges
    assert ("orders", "sqs_queue:payments-queue", "produces") in edges
    # payments reads Orders, writes Payments, publishes SNS
    assert ("payments", "dynamodb_table:Orders", "reads") in edges
    assert ("payments", "dynamodb_table:Payments", "writes") in edges
    assert ("payments", "sns_topic:payment-events", "produces") in edges
    # notifications reads SecretsManager
    assert ("notifications", "secrets_manager_secret:webhook/url", "reads") in edges


@pytest.mark.asyncio
async def test_graph_critic_passes_on_complete_graph(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    with patch("agent_harness.discovery.dependency_grapher._run_agent",
               new=AsyncMock(return_value="{}")):
        g = await build_graph(repo_id="synth", repo_root=FIXTURE, inventory=_inv())
    report = critique_graph(g, repo_root=FIXTURE, inventory=_inv())
    assert report.verdict == "PASS", report.reasons


def test_graph_critic_fails_when_edge_missing():
    from agent_harness.discovery.artifacts import DependencyGraph, GraphNode, GraphEdge
    g = DependencyGraph(
        nodes=[GraphNode(id="orders", kind="module", attrs={})],
        edges=[],  # no edges at all
    )
    report = critique_graph(g, repo_root=FIXTURE, inventory=_inv())
    assert report.verdict == "FAIL"
    assert any("Orders" in r or "put_item" in r for r in report.reasons)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dependency_grapher.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `critics/__init__.py` and `critics/base.py`**

```python
# agent_harness/discovery/critics/__init__.py
"""Critic agents for discovery stages."""
```

```python
# agent_harness/discovery/critics/base.py
"""Shared utilities for critics."""
from __future__ import annotations
import json
from ..artifacts import CriticReport


def parse_critic_response(text: str) -> CriticReport:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text
        if text.endswith("```"):
            text = text[:-3]
    data = json.loads(text)
    return CriticReport.model_validate(data)
```

- [ ] **Step 4: Implement `dependency_grapher.py`**

```python
# agent_harness/discovery/dependency_grapher.py
"""DependencyGrapher — deterministic-first graph build with LLM fallback."""
from __future__ import annotations

import logging
from pathlib import Path

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import DependencyGraph, Inventory
from .tools.aws_sdk_patterns import resolve
from .tools.graph_io import GraphBuilder, save
from .tools.tree_sitter_py import extract_boto3_calls, parse_imports
from . import paths

logger = logging.getLogger("discovery.grapher")


async def _run_agent(message: str) -> str:
    """LLM invocation seam — patched in tests."""
    agent = create_agent(role="dependency_grapher",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def build_graph(repo_id: str, repo_root: Path,
                      inventory: Inventory,
                      extra_instructions: str = "") -> DependencyGraph:
    """Build the graph deterministically; invoke LLM only for ambiguous calls."""
    repo_root = Path(repo_root).resolve()
    builder = GraphBuilder()
    module_paths: dict[str, Path] = {}

    for m in inventory.modules:
        builder.add_module(m.id, attrs={"path": m.path, "language": m.language})
        module_paths[m.id] = repo_root / m.path

    module_ids = set(module_paths)
    ambiguous_calls: list[tuple[str, str]] = []  # (module_id, file:line context)

    for m in inventory.modules:
        for py_file in module_paths[m.id].rglob("*.py"):
            # Imports → module-level edges
            for imp in parse_imports(str(py_file)):
                target = _import_to_module(imp.module, m.id, module_ids)
                if target and target != m.id:
                    builder.add_edge(m.id, target, "imports")

            # boto3 calls → resource edges
            for call in extract_boto3_calls(str(py_file)):
                ref = resolve(call)
                if ref is None:
                    ambiguous_calls.append(
                        (m.id, f"{call.file}:{call.line} {call.service}.{call.method}")
                    )
                    continue
                node = builder.add_resource(ref.kind, ref.name)
                builder.add_edge(m.id, node, ref.access)

    # LLM disambiguation only if needed.
    if ambiguous_calls:
        listing = "\n".join(f"- module={mid}: {ctx}" for mid, ctx in ambiguous_calls)
        msg = (
            "Resolve these ambiguous boto3 call sites to (resource_kind, resource_name).\n"
            "Return JSON: [{\"module\": \"...\", \"resource_kind\": \"...\", \"resource_name\": \"...\", \"access\": \"reads|writes|produces|consumes|invokes\"}]\n\n"
            f"{listing}\n\n{extra_instructions}"
        )
        raw = await _run_agent(msg)
        try:
            import json
            for entry in json.loads(_strip_fences(raw)):
                node = builder.add_resource(entry["resource_kind"], entry["resource_name"])
                builder.add_edge(entry["module"], node, entry["access"])
        except Exception as exc:
            logger.warning("LLM disambiguation skipped: %s", exc)

    g = builder.build()
    save(g, paths.graph_path(repo_id))
    return g


def _import_to_module(module: str, current: str, module_ids: set[str]) -> str | None:
    """Map a Python import to a known module id, if any.

    Heuristic: take the first path segment of the import; if it matches an
    inventory module id, that's our target.
    """
    if module.startswith("."):
        return None  # relative within the same module — skip
    head = module.split(".", 1)[0]
    return head if head in module_ids else None


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
```

- [ ] **Step 5: Implement `critics/graph_critic.py`**

```python
# agent_harness/discovery/critics/graph_critic.py
"""Validate a DependencyGraph against a deterministic re-scan of source."""
from __future__ import annotations

from pathlib import Path

from ..artifacts import CriticReport, DependencyGraph, Inventory
from ..tools.aws_sdk_patterns import resolve
from ..tools.tree_sitter_py import extract_boto3_calls, parse_imports


def critique_graph(graph: DependencyGraph, repo_root: Path,
                   inventory: Inventory) -> CriticReport:
    repo_root = Path(repo_root).resolve()
    edges = {(e.src, e.dst, e.kind) for e in graph.edges}
    reasons: list[str] = []
    suggestions: list[str] = []

    module_ids = {m.id for m in inventory.modules}

    for m in inventory.modules:
        for py_file in (repo_root / m.path).rglob("*.py"):
            for imp in parse_imports(str(py_file)):
                if imp.module.startswith("."):
                    continue
                head = imp.module.split(".", 1)[0]
                if head in module_ids and head != m.id:
                    if (m.id, head, "imports") not in edges:
                        reasons.append(
                            f"missing import edge {m.id} -> {head} ({py_file}:{imp.line})"
                        )

            for call in extract_boto3_calls(str(py_file)):
                ref = resolve(call)
                if ref is None:
                    continue  # ambiguous; not the critic's job to resolve
                target = f"{ref.kind}:{ref.name}" if ref.name else None
                if target is None:
                    continue
                edge = (m.id, target, ref.access)
                if edge not in edges:
                    reasons.append(
                        f"missing edge {m.id} -[{ref.access}]-> {target} "
                        f"(call {call.service}.{call.method} at {py_file}:{call.line})"
                    )

    if reasons:
        suggestions.append("Re-run grapher; ensure aws_sdk_patterns covers each call.")
    return CriticReport(
        verdict="PASS" if not reasons else "FAIL",
        reasons=reasons,
        suggestions=suggestions,
    )
```

- [ ] **Step 6: Create prompt stubs**

```markdown
# agent_harness/discovery/prompts/dependency_grapher.md
# Dependency Grapher

You receive a list of `boto3`/`aioboto3` call sites from Python source where
the deterministic rule library could not infer the target AWS resource (e.g.,
the resource name is computed at runtime, or the SDK method is unusual).

## Output
Return ONLY a JSON array (no prose, no fences):

```
[
  {
    "module": "<inventory module id>",
    "resource_kind": "dynamodb_table|s3_bucket|sqs_queue|sns_topic|kinesis_stream|secrets_manager_secret|lambda_function",
    "resource_name": "<best literal you can recover, or null>",
    "access": "reads|writes|produces|consumes|invokes"
  }
]
```

## Rules
- Use `read_file` and `search_files` to locate the call site and inspect any
  variables or env-var lookups feeding the resource name.
- If the resource name is genuinely unknowable, set it to `null`.
- Pick the closest matching `access` from the enum.
- If a call is unrelated to AWS, OMIT it.
```

```markdown
# agent_harness/discovery/prompts/critic_graph.md
# Graph Critic

(Reserved for future LLM-based graph critique. The current implementation in
`graph_critic.py` is fully deterministic and does not invoke an LLM. This file
exists so the prompt loader does not warn.)
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_dependency_grapher.py -v`
Expected: 3 PASS.

- [ ] **Step 8: Commit**

```bash
git add agent_harness/discovery/dependency_grapher.py \
        agent_harness/discovery/critics/ \
        agent_harness/discovery/prompts/dependency_grapher.md \
        agent_harness/discovery/prompts/critic_graph.md \
        tests/test_dependency_grapher.py
git commit -m "feat(discovery): DependencyGrapher (deterministic-first) + graph critic"
```

---

## Task 10: BRDExtractor + brd_critic

**Files:**
- Create: `agent_harness/discovery/brd_extractor.py`
- Create: `agent_harness/discovery/critics/brd_critic.py`
- Create: `agent_harness/discovery/prompts/brd_extractor.md`
- Create: `agent_harness/discovery/prompts/critic_brd.md`
- Test: `tests/test_brd_extractor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_brd_extractor.py
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, DependencyGraph, GraphNode, GraphEdge,
)
from agent_harness.discovery.brd_extractor import extract_brds
from agent_harness.discovery.critics.brd_critic import critique_brds
from agent_harness.discovery import paths

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


def _inv():
    return Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 8, "total_loc": 60,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py", loc=14, config_files=[]),
        ],
    )


def _graph():
    return DependencyGraph(
        nodes=[
            GraphNode(id="orders", kind="module", attrs={}),
            GraphNode(id="dynamodb_table:Orders", kind="aws_resource",
                      attrs={"resource_kind": "dynamodb_table"}),
        ],
        edges=[GraphEdge(src="orders", dst="dynamodb_table:Orders", kind="writes")],
    )


@pytest.mark.asyncio
async def test_extract_brds_writes_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    canned = (
        "# Module BRD: orders\n\n"
        "## Purpose\nReceives orders.\n\n"
        "## Triggers\nAPI Gateway POST /orders.\n\n"
        "## Business Rules\n- Idempotent on order id.\n\n"
        "## Side Effects\n- Writes dynamodb_table:Orders.\n\n"
        "## Error Paths\n- Returns 500 on DynamoDB failure.\n"
    )
    sysbrd = "# System BRD\n\n## Cross-Module Workflows\nNone.\n"
    with patch("agent_harness.discovery.brd_extractor._run_module_agent",
               new=AsyncMock(return_value=canned)), \
         patch("agent_harness.discovery.brd_extractor._run_system_agent",
               new=AsyncMock(return_value=sysbrd)):
        modules, system = await extract_brds(
            repo_id="synth", repo_root=FIXTURE, inventory=_inv(), graph=_graph(),
        )
    assert paths.module_brd_path("synth", "orders").exists()
    assert paths.system_brd_path("synth").exists()
    assert "Business Rules" in modules[0].body
    assert "System BRD" in system.body


def test_brd_critic_passes_when_all_required_sections_present(tmp_path):
    from agent_harness.discovery.artifacts import ModuleBRD, SystemBRD
    body = (
        "# Module BRD: orders\n\n"
        "## Business Rules\n- rule\n\n"
        "## Error Paths\n- err\n\n"
        "## Side Effects\n- writes dynamodb_table:Orders\n"
    )
    report = critique_brds(
        modules=[ModuleBRD(module_id="orders", body=body)],
        system=SystemBRD(body="ok"),
        inventory=_inv(),
        graph=_graph(),
    )
    assert report.verdict == "PASS", report.reasons


def test_brd_critic_fails_when_business_rules_missing():
    from agent_harness.discovery.artifacts import ModuleBRD, SystemBRD
    body = "# Module BRD: orders\n\n## Side Effects\n- writes dynamodb_table:Orders\n"
    report = critique_brds(
        modules=[ModuleBRD(module_id="orders", body=body)],
        system=SystemBRD(body="ok"),
        inventory=_inv(),
        graph=_graph(),
    )
    assert report.verdict == "FAIL"
    assert any("business_rules" in r.lower() or "business rules" in r.lower()
               for r in report.reasons)


def test_brd_critic_fails_when_module_missing():
    from agent_harness.discovery.artifacts import SystemBRD
    report = critique_brds(
        modules=[],
        system=SystemBRD(body="ok"),
        inventory=_inv(),
        graph=_graph(),
    )
    assert report.verdict == "FAIL"
    assert any("orders" in r for r in report.reasons)


def test_brd_critic_fails_when_resource_unreferenced():
    from agent_harness.discovery.artifacts import ModuleBRD, SystemBRD
    body = (
        "# Module BRD: orders\n\n"
        "## Business Rules\n- r\n\n"
        "## Error Paths\n- e\n\n"
        "## Side Effects\n- nothing\n"
    )
    report = critique_brds(
        modules=[ModuleBRD(module_id="orders", body=body)],
        system=SystemBRD(body="ok"),
        inventory=_inv(),
        graph=_graph(),
    )
    assert report.verdict == "FAIL"
    assert any("Orders" in r for r in report.reasons)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_brd_extractor.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `brd_extractor.py`**

```python
# agent_harness/discovery/brd_extractor.py
"""BRDExtractor — produces per-module + system BRD markdown."""
from __future__ import annotations

import logging
from pathlib import Path

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import DependencyGraph, Inventory, ModuleBRD, SystemBRD
from . import paths

logger = logging.getLogger("discovery.brd")


async def _run_module_agent(message: str) -> str:
    agent = create_agent(role="brd_extractor",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def _run_system_agent(message: str) -> str:
    agent = create_agent(role="brd_extractor",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def extract_brds(repo_id: str, repo_root: Path,
                       inventory: Inventory, graph: DependencyGraph,
                       extra_instructions: str = "") -> tuple[list[ModuleBRD], SystemBRD]:
    repo_root = Path(repo_root).resolve()
    modules: list[ModuleBRD] = []

    for m in inventory.modules:
        sources = _collect_sources(repo_root / m.path)
        edges = [e for e in graph.edges if e.src == m.id or e.dst == m.id]
        msg = (
            f"Write a BRD markdown for module `{m.id}`.\n\n"
            f"Required sections: Purpose, Triggers, Inputs, Outputs, Business Rules, "
            f"Side Effects, Error Paths, Non-Functionals, PII/Compliance.\n\n"
            f"## Module dependency edges\n{_render_edges(edges)}\n\n"
            f"## Source\n{sources}\n\n{extra_instructions}\n\n"
            f"Output ONLY the markdown body."
        )
        body = await _run_module_agent(msg)
        brd = ModuleBRD(module_id=m.id, body=body)
        out = paths.module_brd_path(repo_id, m.id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
        modules.append(brd)

    sys_msg = (
        "Write `_system.md` summarizing cross-module workflows and shared invariants.\n\n"
        f"## All edges\n{_render_edges(graph.edges)}\n\n"
        "Output ONLY the markdown body."
    )
    sys_body = await _run_system_agent(sys_msg)
    paths.system_brd_path(repo_id).write_text(sys_body, encoding="utf-8")
    return modules, SystemBRD(body=sys_body)


def _collect_sources(module_dir: Path, max_chars: int = 60_000) -> str:
    chunks: list[str] = []
    used = 0
    for f in sorted(module_dir.rglob("*.py")):
        text = f.read_text(encoding="utf-8", errors="replace")
        block = f"--- {f} ---\n{text}\n"
        if used + len(block) > max_chars:
            chunks.append(f"--- {f} (truncated) ---\n")
            break
        chunks.append(block)
        used += len(block)
    return "\n".join(chunks)


def _render_edges(edges) -> str:
    return "\n".join(f"- {e.src} -[{e.kind}]-> {e.dst}" for e in edges)
```

- [ ] **Step 4: Implement `critics/brd_critic.py`**

```python
# agent_harness/discovery/critics/brd_critic.py
"""Deterministic BRD critic — checks coverage and required sections."""
from __future__ import annotations

import re

from ..artifacts import CriticReport, DependencyGraph, Inventory, ModuleBRD, SystemBRD

REQUIRED_SECTIONS = ("Business Rules", "Error Paths", "Side Effects")


def critique_brds(modules: list[ModuleBRD], system: SystemBRD,
                  inventory: Inventory, graph: DependencyGraph) -> CriticReport:
    reasons: list[str] = []
    by_id = {b.module_id: b for b in modules}

    # 1. Every public handler module has a BRD.
    for m in inventory.modules:
        if m.id not in by_id:
            reasons.append(f"BRD missing for module {m.id}")

    # 2. Required sections present and non-empty.
    for b in modules:
        for section in REQUIRED_SECTIONS:
            if not _section_has_content(b.body, section):
                reasons.append(f"module {b.module_id}: missing {section} section")

    # 3. Every shared AWS resource referenced in some BRD's side-effects.
    resource_ids = {n.id for n in graph.nodes if n.kind == "aws_resource"}
    referenced = set()
    for b in modules:
        side = _section_text(b.body, "Side Effects")
        for rid in resource_ids:
            short = rid.split(":", 1)[-1]
            if short and short in side:
                referenced.add(rid)
    missing = resource_ids - referenced
    for rid in sorted(missing):
        reasons.append(f"AWS resource {rid} not referenced by any BRD's Side Effects")

    return CriticReport(
        verdict="PASS" if not reasons else "FAIL",
        reasons=reasons,
        suggestions=[],
    )


def _section_text(body: str, name: str) -> str:
    pattern = rf"^##\s+{re.escape(name)}\s*$(.*?)(?=^##\s|\Z)"
    m = re.search(pattern, body, flags=re.MULTILINE | re.DOTALL)
    return (m.group(1) if m else "").strip()


def _section_has_content(body: str, name: str) -> bool:
    text = _section_text(body, name)
    # Must contain at least one bullet or non-trivial line.
    for line in text.splitlines():
        line = line.strip()
        if line and line != "- " and not line.startswith("#"):
            return True
    return False
```

- [ ] **Step 5: Create prompt files**

```markdown
# agent_harness/discovery/prompts/brd_extractor.md
# BRD Extractor

You receive a single Lambda module's source and its dependency edges, and you
write a Business Requirements Document in markdown.

## Required sections (use exactly these `## ` headings)
- Purpose
- Triggers
- Inputs
- Outputs
- Business Rules        ← must contain at least one bullet
- Side Effects          ← must reference every AWS resource the module touches by name
- Error Paths           ← must contain at least one bullet
- Non-Functionals       ← latency, idempotency, ordering
- PII/Compliance

## Rules
- Write what the code DOES, not what you think it should do.
- For each AWS resource (DynamoDB table name, S3 bucket name, SQS queue, SNS
  topic, Secrets Manager secret), reference the literal name in Side Effects.
- Output ONLY the markdown body — no preamble, no fences.
```

```markdown
# agent_harness/discovery/prompts/critic_brd.md
# BRD Critic
Reserved — current implementation is deterministic.
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_brd_extractor.py -v`
Expected: 5 PASS.

- [ ] **Step 7: Commit**

```bash
git add agent_harness/discovery/brd_extractor.py \
        agent_harness/discovery/critics/brd_critic.py \
        agent_harness/discovery/prompts/brd_extractor.md \
        agent_harness/discovery/prompts/critic_brd.md \
        tests/test_brd_extractor.py
git commit -m "feat(discovery): BRDExtractor agent + deterministic BRD critic"
```

---

## Task 11: Architect + design_critic

**Files:**
- Create: `agent_harness/discovery/architect.py`
- Create: `agent_harness/discovery/critics/design_critic.py`
- Create: `agent_harness/discovery/prompts/architect.md`
- Create: `agent_harness/discovery/prompts/critic_design.md`
- Test: `tests/test_architect.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_architect.py
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, DependencyGraph, GraphNode, GraphEdge,
    ModuleBRD, SystemBRD, ModuleDesign, SystemDesign,
)
from agent_harness.discovery.architect import design
from agent_harness.discovery.critics.design_critic import critique_designs
from agent_harness.discovery import paths

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


def _inv():
    return Inventory(
        repo_meta={"root_path": str(FIXTURE), "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path="orders", language="python",
                              handler_entrypoint="orders/handler.py",
                              loc=14, config_files=[])],
    )


def _graph():
    return DependencyGraph(
        nodes=[
            GraphNode(id="orders", kind="module", attrs={}),
            GraphNode(id="dynamodb_table:Orders", kind="aws_resource",
                      attrs={"resource_kind": "dynamodb_table"}),
        ],
        edges=[GraphEdge(src="orders", dst="dynamodb_table:Orders", kind="writes")],
    )


@pytest.mark.asyncio
async def test_design_writes_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    module_design = (
        "# Module Design: orders\n\n"
        "## Function Plan\nFlex consumption.\n\n"
        "## Trigger Bindings\n- HTTP trigger.\n\n"
        "## State Mapping\n- dynamodb_table:Orders → Cosmos DB NoSQL container.\n\n"
        "## Secrets\n- None.\n\n"
        "## Identity\n- Managed Identity.\n\n"
        "## IaC\n- Bicep.\n\n"
        "## Observability\n- App Insights.\n"
    )
    system = "# System Design\n\n## Strangler Seams\nMigrate orders first.\n"
    brd = ModuleBRD(module_id="orders", body=(
        "## Triggers\nAPI Gateway POST /orders.\n## Side Effects\n- writes dynamodb_table:Orders\n"
    ))
    sys_brd = SystemBRD(body="ok")
    with patch("agent_harness.discovery.architect._run_module_agent",
               new=AsyncMock(return_value=module_design)), \
         patch("agent_harness.discovery.architect._run_system_agent",
               new=AsyncMock(return_value=system)):
        modules, sysd = await design(
            repo_id="synth", inventory=_inv(), graph=_graph(),
            module_brds=[brd], system_brd=sys_brd,
        )
    assert paths.module_design_path("synth", "orders").exists()
    assert paths.system_design_path("synth").exists()
    assert "Cosmos DB" in modules[0].body


def test_design_critic_fails_when_resource_unmapped():
    md = ModuleDesign(module_id="orders", body=(
        "## State Mapping\n- nothing\n"
    ))
    sd = SystemDesign(body="ok")
    report = critique_designs(
        designs=[md], system=sd, inventory=_inv(),
        graph=_graph(), module_brds=[ModuleBRD(module_id="orders", body="x")],
    )
    assert report.verdict == "FAIL"
    assert any("dynamodb_table" in r for r in report.reasons)


def test_design_critic_passes_when_resource_mapped():
    md = ModuleDesign(module_id="orders", body=(
        "## State Mapping\n- dynamodb_table:Orders → Cosmos DB NoSQL\n"
    ))
    sd = SystemDesign(body="ok")
    report = critique_designs(
        designs=[md], system=sd, inventory=_inv(), graph=_graph(),
        module_brds=[ModuleBRD(module_id="orders", body="x")],
    )
    assert report.verdict == "PASS"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_architect.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `architect.py`**

```python
# agent_harness/discovery/architect.py
"""Architect agent — produces target Azure design markdown."""
from __future__ import annotations

import logging

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import (
    DependencyGraph, Inventory, ModuleBRD, ModuleDesign, SystemBRD, SystemDesign,
)
from . import paths

logger = logging.getLogger("discovery.architect")


async def _run_module_agent(message: str) -> str:
    agent = create_agent(role="architect",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def _run_system_agent(message: str) -> str:
    agent = create_agent(role="architect",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def design(repo_id: str, inventory: Inventory, graph: DependencyGraph,
                 module_brds: list[ModuleBRD], system_brd: SystemBRD,
                 extra_instructions: str = "") -> tuple[list[ModuleDesign], SystemDesign]:
    designs: list[ModuleDesign] = []
    by_id = {b.module_id: b for b in module_brds}

    for m in inventory.modules:
        brd = by_id.get(m.id)
        if brd is None:
            continue
        edges = [e for e in graph.edges if e.src == m.id or e.dst == m.id]
        msg = (
            f"Produce the Azure target design markdown for module `{m.id}`.\n\n"
            f"## Required sections (## headings):\n"
            f"- Function Plan (Consumption/Premium/Flex)\n"
            f"- Trigger Bindings (one entry per source AWS trigger)\n"
            f"- State Mapping (one entry per AWS resource the module touches)\n"
            f"- Secrets\n- Identity\n- IaC (Bicep)\n- Observability\n\n"
            f"## Module BRD\n{brd.body}\n\n"
            f"## Module edges\n" + "\n".join(f"- {e.src} -[{e.kind}]-> {e.dst}" for e in edges)
            + f"\n\n{extra_instructions}\n\nOutput ONLY the markdown body."
        )
        body = await _run_module_agent(msg)
        d = ModuleDesign(module_id=m.id, body=body)
        out = paths.module_design_path(repo_id, m.id)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
        designs.append(d)

    sys_msg = (
        "Produce `_system.md` covering Strangler Seams, Anti-Corruption Layers, "
        "and Shared Resource Migration Ordering.\n\n"
        f"## System BRD\n{system_brd.body}\n\nOutput ONLY the markdown body."
    )
    sys_body = await _run_system_agent(sys_msg)
    paths.system_design_path(repo_id).write_text(sys_body, encoding="utf-8")
    return designs, SystemDesign(body=sys_body)
```

- [ ] **Step 4: Implement `critics/design_critic.py`**

```python
# agent_harness/discovery/critics/design_critic.py
"""Deterministic design critic — verifies every resource has a mapping."""
from __future__ import annotations

import re

from ..artifacts import (
    CriticReport, DependencyGraph, Inventory, ModuleBRD, ModuleDesign, SystemDesign,
)


def critique_designs(designs: list[ModuleDesign], system: SystemDesign,
                     inventory: Inventory, graph: DependencyGraph,
                     module_brds: list[ModuleBRD]) -> CriticReport:
    reasons: list[str] = []
    by_id = {d.module_id: d for d in designs}

    for m in inventory.modules:
        d = by_id.get(m.id)
        if d is None:
            reasons.append(f"design missing for module {m.id}")
            continue

        module_resources = {
            e.dst for e in graph.edges
            if e.src == m.id and ":" in e.dst  # resource ids are 'kind:name'
        }
        state_section = _section_text(d.body, "State Mapping")
        for rid in module_resources:
            kind, _, name = rid.partition(":")
            # The design must mention either the literal name or the kind+name combo.
            if name and name not in state_section and kind not in state_section:
                reasons.append(
                    f"module {m.id}: resource {rid} not mapped in State Mapping section"
                )

    return CriticReport(
        verdict="PASS" if not reasons else "FAIL",
        reasons=reasons,
        suggestions=[],
    )


def _section_text(body: str, name: str) -> str:
    m = re.search(rf"^##\s+{re.escape(name)}\s*$(.*?)(?=^##\s|\Z)",
                  body, flags=re.MULTILINE | re.DOTALL)
    return (m.group(1) if m else "").strip()
```

- [ ] **Step 5: Create prompt files**

```markdown
# agent_harness/discovery/prompts/architect.md
# Azure Architect

Translate the BRD + dependency edges into a target Azure Functions design.

## Mapping reference (use these by default)
| AWS                    | Azure                                       |
|------------------------|---------------------------------------------|
| API Gateway            | HTTP trigger                                |
| SQS                    | Service Bus queue trigger                   |
| SNS                    | Event Grid (or Service Bus topic)           |
| S3                     | Blob trigger or Event Grid                  |
| DynamoDB Streams       | Cosmos DB change feed                       |
| Kinesis                | Event Hubs                                  |
| EventBridge            | Event Grid                                  |
| DynamoDB table         | Cosmos DB NoSQL container                   |
| RDS Postgres           | Azure DB for PostgreSQL                     |
| Secrets Manager        | Key Vault                                   |
| IAM Role               | Managed Identity                            |
| CloudWatch             | Application Insights                        |

## Required sections (## headings, exactly):
Function Plan, Trigger Bindings, State Mapping, Secrets, Identity, IaC, Observability.

In **State Mapping**, list one bullet per AWS resource that appears in the
module's edges, by literal name. Bullet must reference the resource and the
target Azure service.

Output ONLY the markdown body.
```

```markdown
# agent_harness/discovery/prompts/critic_design.md
# Design Critic
Reserved — current implementation is deterministic.
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_architect.py -v`
Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add agent_harness/discovery/architect.py \
        agent_harness/discovery/critics/design_critic.py \
        agent_harness/discovery/prompts/architect.md \
        agent_harness/discovery/prompts/critic_design.md \
        tests/test_architect.py
git commit -m "feat(discovery): Architect agent + deterministic design critic"
```

---

## Task 12: StoryDecomposer + story_critic

**Files:**
- Create: `agent_harness/discovery/story_decomposer.py`
- Create: `agent_harness/discovery/critics/story_critic.py`
- Create: `agent_harness/discovery/prompts/story_decomposer.md`
- Create: `agent_harness/discovery/prompts/critic_story.md`
- Test: `tests/test_story_decomposer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_story_decomposer.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, DependencyGraph, GraphNode, GraphEdge,
    ModuleBRD, SystemBRD, ModuleDesign, SystemDesign, Stories, Story,
    Epic, AcceptanceCriterion,
)
from agent_harness.discovery.story_decomposer import decompose
from agent_harness.discovery.critics.story_critic import critique_stories
from agent_harness.discovery import paths


def _inv():
    return Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[
            ModuleRecord(id="orders", path="orders", language="python",
                         handler_entrypoint="orders/handler.py", loc=10, config_files=[]),
            ModuleRecord(id="payments", path="payments", language="python",
                         handler_entrypoint="payments/handler.py", loc=10, config_files=[]),
        ],
    )


@pytest.mark.asyncio
async def test_decompose_writes_stories(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    canned = Stories(
        epics=[
            Epic(id="E1", module_id="orders", title="Migrate orders", story_ids=["S1"]),
            Epic(id="E2", module_id="payments", title="Migrate payments", story_ids=["S2"]),
        ],
        stories=[
            Story(id="S1", epic_id="E1", title="HTTP function",
                  description="d", acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=[], blocks=[], estimate="M"),
            Story(id="S2", epic_id="E2", title="SQS consumer",
                  description="d", acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S1"], blocks=[], estimate="M"),
        ],
    ).model_dump_json()

    with patch("agent_harness.discovery.story_decomposer._run_agent",
               new=AsyncMock(return_value=canned)):
        stories = await decompose(
            repo_id="synth",
            inventory=_inv(),
            graph=DependencyGraph(nodes=[], edges=[]),
            module_brds=[ModuleBRD(module_id="orders", body=""),
                         ModuleBRD(module_id="payments", body="")],
            system_brd=SystemBRD(body=""),
            module_designs=[ModuleDesign(module_id="orders", body=""),
                            ModuleDesign(module_id="payments", body="")],
            system_design=SystemDesign(body=""),
        )

    assert paths.stories_path("synth").exists()
    assert {e.id for e in stories.epics} == {"E1", "E2"}


def test_story_critic_passes_on_valid_stories():
    s = Stories(
        epics=[Epic(id="E1", module_id="orders", title="t", story_ids=["S1"])],
        stories=[Story(id="S1", epic_id="E1", title="t", description="d",
                       acceptance_criteria=[AcceptanceCriterion(text="ac")],
                       depends_on=[], blocks=[], estimate="M")],
    )
    inv = Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path=".", language="python",
                              handler_entrypoint=".", loc=1, config_files=[])],
    )
    report = critique_stories(s, inv)
    assert report.verdict == "PASS"


def test_story_critic_fails_on_unknown_dep():
    s = Stories(
        epics=[Epic(id="E1", module_id="orders", title="t", story_ids=["S1"])],
        stories=[Story(id="S1", epic_id="E1", title="t", description="d",
                       acceptance_criteria=[AcceptanceCriterion(text="ac")],
                       depends_on=["GHOST"], blocks=[], estimate="M")],
    )
    inv = Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path=".", language="python",
                              handler_entrypoint=".", loc=1, config_files=[])],
    )
    report = critique_stories(s, inv)
    assert report.verdict == "FAIL"
    assert any("GHOST" in r for r in report.reasons)


def test_story_critic_fails_on_cycle():
    s = Stories(
        epics=[Epic(id="E1", module_id="orders", title="t", story_ids=["S1", "S2"])],
        stories=[
            Story(id="S1", epic_id="E1", title="t", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S2"], blocks=[], estimate="M"),
            Story(id="S2", epic_id="E1", title="t", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S1"], blocks=[], estimate="M"),
        ],
    )
    inv = Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path=".", language="python",
                              handler_entrypoint=".", loc=1, config_files=[])],
    )
    report = critique_stories(s, inv)
    assert report.verdict == "FAIL"
    assert any("cycle" in r.lower() for r in report.reasons)


def test_story_critic_fails_when_module_has_no_epic():
    s = Stories(epics=[], stories=[])
    inv = Inventory(
        repo_meta={"root_path": "/r", "total_files": 1, "total_loc": 1,
                   "discovered_at": "2026-04-14T00:00:00Z"},
        modules=[ModuleRecord(id="orders", path=".", language="python",
                              handler_entrypoint=".", loc=1, config_files=[])],
    )
    report = critique_stories(s, inv)
    assert report.verdict == "FAIL"
    assert any("orders" in r for r in report.reasons)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_story_decomposer.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `story_decomposer.py`**

```python
# agent_harness/discovery/story_decomposer.py
"""StoryDecomposer agent — turns BRDs+designs into epics and stories."""
from __future__ import annotations

import logging

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import (
    DependencyGraph, Inventory, ModuleBRD, ModuleDesign, Stories, SystemBRD, SystemDesign,
)
from . import paths

logger = logging.getLogger("discovery.stories")


async def _run_agent(message: str) -> str:
    agent = create_agent(role="story_decomposer",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def decompose(repo_id: str, inventory: Inventory, graph: DependencyGraph,
                    module_brds: list[ModuleBRD], system_brd: SystemBRD,
                    module_designs: list[ModuleDesign], system_design: SystemDesign,
                    extra_instructions: str = "") -> Stories:
    msg = (
        "Decompose the migration into epics and stories. Return ONLY a JSON object "
        "matching the Stories schema with keys: epics, stories.\n\n"
        f"## Inventory modules\n{', '.join(m.id for m in inventory.modules)}\n\n"
        f"## System BRD\n{system_brd.body}\n\n"
        f"## System Design\n{system_design.body}\n\n"
        f"## Per-module BRDs\n" + "\n\n".join(f"### {b.module_id}\n{b.body}" for b in module_brds) + "\n\n"
        f"## Per-module Designs\n" + "\n\n".join(f"### {d.module_id}\n{d.body}" for d in module_designs) + "\n\n"
        f"## Resource edges\n" + "\n".join(f"- {e.src} -[{e.kind}]-> {e.dst}" for e in graph.edges) + "\n\n"
        f"{extra_instructions}\n\n"
        "Rules:\n"
        "- At least one epic per module.\n"
        "- Every story has at least one acceptance_criteria entry.\n"
        "- depends_on must reference story ids that exist in this output.\n"
        "- The dependency subgraph must be acyclic.\n"
    )
    raw = await _run_agent(msg)
    stories = Stories.model_validate_json(_strip_fences(raw))
    out = paths.stories_path(repo_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(stories.model_dump_json(indent=2), encoding="utf-8")
    return stories


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
```

- [ ] **Step 4: Implement `critics/story_critic.py`**

```python
# agent_harness/discovery/critics/story_critic.py
"""Deterministic story critic — DAG well-formedness and coverage."""
from __future__ import annotations

from collections import defaultdict, deque

from ..artifacts import CriticReport, Inventory, Stories


def critique_stories(stories: Stories, inventory: Inventory) -> CriticReport:
    reasons: list[str] = []
    by_id = {s.id: s for s in stories.stories}

    for s in stories.stories:
        if not s.acceptance_criteria:
            reasons.append(f"story {s.id}: must have at least one acceptance criterion")
        for dep in s.depends_on:
            if dep not in by_id:
                reasons.append(f"story {s.id}: depends_on unknown story {dep}")

    epic_modules = {e.module_id for e in stories.epics}
    for m in inventory.modules:
        if m.id not in epic_modules:
            reasons.append(f"module {m.id}: no epic produced")

    # Cycle detection via Kahn's.
    indeg = {sid: 0 for sid in by_id}
    succ = defaultdict(list)
    for s in stories.stories:
        for dep in s.depends_on:
            if dep in by_id:
                indeg[s.id] += 1
                succ[dep].append(s.id)
    q = deque(sid for sid, d in indeg.items() if d == 0)
    seen = 0
    while q:
        sid = q.popleft()
        seen += 1
        for n in succ[sid]:
            indeg[n] -= 1
            if indeg[n] == 0:
                q.append(n)
    if seen != len(by_id):
        unresolved = sorted(set(by_id) - set(s for s in by_id if indeg[s] == 0))
        reasons.append(f"cycle in story dependency graph involving: {unresolved}")

    return CriticReport(
        verdict="PASS" if not reasons else "FAIL",
        reasons=reasons,
        suggestions=[],
    )
```

- [ ] **Step 5: Create prompt files**

```markdown
# agent_harness/discovery/prompts/story_decomposer.md
# Story Decomposer

You decompose a multi-module Azure migration into epics and user stories.

## Output
Return ONLY a JSON object (no fences, no prose) matching:

```
{
  "epics": [
    { "id": "<E#>", "module_id": "<inventory module id>", "title": "...",
      "story_ids": ["S#", ...] }
  ],
  "stories": [
    { "id": "<S#>", "epic_id": "<E#>", "title": "...", "description": "...",
      "acceptance_criteria": [{"text": "..."}],
      "depends_on": ["S#", ...], "blocks": ["S#", ...],
      "estimate": "S|M|L" }
  ]
}
```

## Rules
- Produce ≥1 epic per inventory module.
- Each story MUST have ≥1 acceptance criterion.
- A story that consumes a resource MUST `depends_on` the story that creates it.
- A story in module X that imports module Y MUST `depends_on` a story from Y's epic.
- Dependency graph MUST be acyclic.
```

```markdown
# agent_harness/discovery/prompts/critic_story.md
# Story Critic
Reserved — current implementation is deterministic.
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_story_decomposer.py -v`
Expected: 5 PASS.

- [ ] **Step 7: Commit**

```bash
git add agent_harness/discovery/story_decomposer.py \
        agent_harness/discovery/critics/story_critic.py \
        agent_harness/discovery/prompts/story_decomposer.md \
        agent_harness/discovery/prompts/critic_story.md \
        tests/test_story_decomposer.py
git commit -m "feat(discovery): StoryDecomposer agent + deterministic story critic"
```

---

## Task 13: Workflow runner — caching, self-heal loop, blocked.md

**Files:**
- Create: `agent_harness/discovery/workflow.py`
- Test: `tests/test_discovery_workflow.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_workflow.py
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.workflow import (
    run_stage, run_discovery, run_planning, hash_inputs,
)
from agent_harness.discovery.artifacts import CriticReport, Inventory
from agent_harness.discovery import paths
from agent_harness.persistence.repository import MigrationRepository

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


@pytest.fixture
def repo(tmp_path):
    r = MigrationRepository(db_path=tmp_path / "test.db")
    r.initialize()
    return r


def test_hash_inputs_stable():
    h1 = hash_inputs("repo", "scanner", ["a", "b"], prompt_version="v1")
    h2 = hash_inputs("repo", "scanner", ["a", "b"], prompt_version="v1")
    assert h1 == h2
    h3 = hash_inputs("repo", "scanner", ["a", "b"], prompt_version="v2")
    assert h1 != h3


@pytest.mark.asyncio
async def test_run_stage_succeeds_first_try(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    repo.create_discovery_run("synth")
    produce = AsyncMock(return_value="ARTIFACT")
    critic = lambda result, ctx: CriticReport(verdict="PASS", reasons=[], suggestions=[])

    out = await run_stage(
        repo=repo, repo_id="synth", stage_name="scanner",
        produce=produce, critic=critic,
        artifact_path=tmp_path / "discovery" / "synth" / "scanner.txt",
        input_hash="h1",
    )

    assert out == "ARTIFACT"
    produce.assert_awaited_once_with("")  # no critic feedback first time
    assert repo.stage_cache_hit("synth", "scanner", "h1")


@pytest.mark.asyncio
async def test_run_stage_self_heals_then_passes(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    repo.create_discovery_run("synth")
    produce = AsyncMock(side_effect=["BAD1", "BAD2", "GOOD"])
    verdicts = iter([
        CriticReport(verdict="FAIL", reasons=["r1"], suggestions=["s1"]),
        CriticReport(verdict="FAIL", reasons=["r2"], suggestions=["s2"]),
        CriticReport(verdict="PASS", reasons=[], suggestions=[]),
    ])
    critic = lambda result, ctx: next(verdicts)

    out = await run_stage(
        repo=repo, repo_id="synth", stage_name="scanner",
        produce=produce, critic=critic,
        artifact_path=tmp_path / "discovery" / "synth" / "scanner.txt",
        input_hash="h1",
    )
    assert out == "GOOD"
    assert produce.await_count == 3
    # Second call must contain critic feedback from first.
    assert "r1" in produce.await_args_list[1].args[0]
    # Third call must contain feedback from second.
    assert "r2" in produce.await_args_list[2].args[0]


@pytest.mark.asyncio
async def test_run_stage_blocks_after_three_fails(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    repo.create_discovery_run("synth")
    produce = AsyncMock(side_effect=["B1", "B2", "B3"])
    critic = lambda result, ctx: CriticReport(verdict="FAIL", reasons=["nope"], suggestions=[])
    artifact = tmp_path / "discovery" / "synth" / "scanner.txt"

    with pytest.raises(RuntimeError, match="blocked"):
        await run_stage(
            repo=repo, repo_id="synth", stage_name="scanner",
            produce=produce, critic=critic,
            artifact_path=artifact, input_hash="h1",
        )
    assert paths.blocked_path("synth", "scanner").exists()
    assert not repo.stage_cache_hit("synth", "scanner", "h1")


@pytest.mark.asyncio
async def test_cache_hit_skips_produce(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    repo.create_discovery_run("synth")
    artifact = tmp_path / "discovery" / "synth" / "scanner.txt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("CACHED")
    repo.cache_stage("synth", "scanner", "h1", str(artifact))
    produce = AsyncMock(return_value="NEW")
    critic = lambda result, ctx: CriticReport(verdict="PASS", reasons=[], suggestions=[])

    out = await run_stage(
        repo=repo, repo_id="synth", stage_name="scanner",
        produce=produce, critic=critic, artifact_path=artifact, input_hash="h1",
    )
    assert out == "CACHED"
    produce.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_workflow.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `workflow.py`**

```python
# agent_harness/discovery/workflow.py
"""Workflow orchestration: hash → cache → 3-attempt self-heal → write artifact."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from ..persistence.repository import MigrationRepository
from .artifacts import (
    Backlog, CriticReport, DependencyGraph, Inventory, Stories,
    ModuleBRD, SystemBRD, ModuleDesign, SystemDesign,
)
from . import paths

logger = logging.getLogger("discovery.workflow")

MAX_ATTEMPTS = 3
PROMPT_VERSION = "v1"  # bump to invalidate every cache row

ProduceFn = Callable[[str], Awaitable[str]]
CriticFn = Callable[[str, dict], CriticReport]


def hash_inputs(repo_id: str, stage_name: str, parts: list[str],
                prompt_version: str = PROMPT_VERSION) -> str:
    h = hashlib.sha256()
    h.update(repo_id.encode())
    h.update(b"\0")
    h.update(stage_name.encode())
    h.update(b"\0")
    h.update(prompt_version.encode())
    for p in parts:
        h.update(b"\0")
        h.update(p.encode("utf-8", errors="replace"))
    return h.hexdigest()


async def run_stage(
    repo: MigrationRepository,
    repo_id: str,
    stage_name: str,
    produce: ProduceFn,
    critic: CriticFn,
    artifact_path: Path,
    input_hash: str,
    critic_context: dict | None = None,
) -> str:
    """Run one stage with caching + 3-attempt self-heal.

    `produce(feedback: str) -> str` returns the raw artifact text.
    `critic(result, ctx) -> CriticReport`.
    Caches on PASS keyed by (repo_id, stage_name, input_hash).
    On 3× FAIL writes blocked.md and raises RuntimeError.
    """
    artifact_path = Path(artifact_path)
    if repo.stage_cache_hit(repo_id, stage_name, input_hash):
        cached = repo.get_cached_stage_path(repo_id, stage_name)
        if cached and Path(cached).exists():
            logger.info("[%s] cache hit %s", stage_name, cached)
            return Path(cached).read_text(encoding="utf-8")

    feedback = ""
    last: CriticReport | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info("[%s] attempt %d/%d", stage_name, attempt, MAX_ATTEMPTS)
        result = await produce(feedback)
        report = critic(result, critic_context or {})
        if report.verdict == "PASS":
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(result, encoding="utf-8")
            repo.cache_stage(repo_id, stage_name, input_hash, str(artifact_path))
            return result
        feedback = (
            "\n\n## Critic feedback (apply this):\n"
            + "\n".join(f"- {r}" for r in report.reasons)
            + ("\n\n### Suggestions\n" + "\n".join(f"- {s}" for s in report.suggestions)
               if report.suggestions else "")
        )
        last = report

    # All attempts failed.
    blocked = paths.blocked_path(repo_id, stage_name)
    blocked.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# Blocked: stage `{stage_name}`\n\n"
        f"Failed after {MAX_ATTEMPTS} self-heal attempts at "
        f"{datetime.now(timezone.utc).isoformat()}.\n\n"
        f"## Last critic report\n```json\n{last.model_dump_json(indent=2) if last else '{}'}\n```\n"
    )
    blocked.write_text(body, encoding="utf-8")
    raise RuntimeError(f"stage {stage_name} blocked after {MAX_ATTEMPTS} attempts")


# ───────────────────────── Stage drivers ────────────────────────────────

async def run_discovery(repo_id: str, repo_path: str,
                        repo: MigrationRepository) -> dict:
    """Run the 5 LLM stages. Returns dict with status + artifact paths."""
    from . import repo_scanner, dependency_grapher, brd_extractor
    from . import architect, story_decomposer
    from .critics.graph_critic import critique_graph
    from .critics.brd_critic import critique_brds
    from .critics.design_critic import critique_designs
    from .critics.story_critic import critique_stories

    repo.create_discovery_run(repo_id)
    root = Path(repo_path).resolve()

    # Stage 1: scanner
    inv_hash = hash_inputs(repo_id, "scanner", [str(root)])

    async def _produce_scanner(feedback: str) -> str:
        inv = await repo_scanner.scan_repo(repo_id, str(root), extra_instructions=feedback)
        return inv.model_dump_json()

    def _critic_scanner(result: str, ctx: dict) -> CriticReport:
        inv = Inventory.model_validate_json(result)
        return repo_scanner.sanity_check(inv, repo_root=root)

    raw_inv = await run_stage(repo, repo_id, "scanner", _produce_scanner, _critic_scanner,
                              paths.inventory_path(repo_id), inv_hash)
    inventory = Inventory.model_validate_json(raw_inv)

    # Stage 2: grapher
    g_hash = hash_inputs(repo_id, "grapher", [raw_inv])

    async def _produce_grapher(feedback: str) -> str:
        g = await dependency_grapher.build_graph(repo_id, root, inventory,
                                                 extra_instructions=feedback)
        return g.model_dump_json()

    def _critic_grapher(result: str, ctx: dict) -> CriticReport:
        g = DependencyGraph.model_validate_json(result)
        return critique_graph(g, root, inventory)

    raw_graph = await run_stage(repo, repo_id, "grapher", _produce_grapher, _critic_grapher,
                                paths.graph_path(repo_id), g_hash)
    graph = DependencyGraph.model_validate_json(raw_graph)

    # Stage 3: brd
    b_hash = hash_inputs(repo_id, "brd", [raw_inv, raw_graph])
    cached_brds: list[ModuleBRD] = []
    cached_sys: SystemBRD | None = None

    async def _produce_brd(feedback: str) -> str:
        nonlocal cached_brds, cached_sys
        cached_brds, cached_sys = await brd_extractor.extract_brds(
            repo_id, root, inventory, graph, extra_instructions=feedback,
        )
        return json.dumps({"modules": [b.model_dump() for b in cached_brds],
                           "system": cached_sys.model_dump()})

    def _critic_brd(result: str, ctx: dict) -> CriticReport:
        return critique_brds(cached_brds, cached_sys, inventory, graph)

    await run_stage(repo, repo_id, "brd", _produce_brd, _critic_brd,
                    paths.brd_dir(repo_id) / "_summary.json", b_hash)

    # Stage 4: architect
    d_hash = hash_inputs(repo_id, "architect", [raw_inv, raw_graph,
                          json.dumps([b.model_dump() for b in cached_brds])])
    cached_designs: list[ModuleDesign] = []
    cached_sys_design: SystemDesign | None = None

    async def _produce_design(feedback: str) -> str:
        nonlocal cached_designs, cached_sys_design
        cached_designs, cached_sys_design = await architect.design(
            repo_id, inventory, graph, cached_brds, cached_sys,
            extra_instructions=feedback,
        )
        return json.dumps({"modules": [d.model_dump() for d in cached_designs],
                           "system": cached_sys_design.model_dump()})

    def _critic_design(result: str, ctx: dict) -> CriticReport:
        return critique_designs(cached_designs, cached_sys_design,
                                inventory, graph, cached_brds)

    await run_stage(repo, repo_id, "architect", _produce_design, _critic_design,
                    paths.design_dir(repo_id) / "_summary.json", d_hash)

    # Stage 5: stories
    s_hash = hash_inputs(repo_id, "stories", [raw_inv, raw_graph,
                          json.dumps([b.model_dump() for b in cached_brds]),
                          json.dumps([d.model_dump() for d in cached_designs])])

    async def _produce_stories(feedback: str) -> str:
        s = await story_decomposer.decompose(
            repo_id, inventory, graph, cached_brds, cached_sys,
            cached_designs, cached_sys_design, extra_instructions=feedback,
        )
        return s.model_dump_json()

    def _critic_stories(result: str, ctx: dict) -> CriticReport:
        s = Stories.model_validate_json(result)
        return critique_stories(s, inventory)

    raw_stories = await run_stage(repo, repo_id, "stories", _produce_stories, _critic_stories,
                                  paths.stories_path(repo_id), s_hash)

    return {
        "status": "ok",
        "stages": ["scanner", "grapher", "brd", "architect", "stories"],
        "artifacts": {
            "inventory": str(paths.inventory_path(repo_id)),
            "graph": str(paths.graph_path(repo_id)),
            "brd_dir": str(paths.brd_dir(repo_id)),
            "design_dir": str(paths.design_dir(repo_id)),
            "stories": str(paths.stories_path(repo_id)),
        },
    }


async def run_planning(repo_id: str, repo: MigrationRepository) -> Backlog:
    """Run the deterministic WaveScheduler over stored artifacts."""
    from .wave_scheduler import schedule

    inv_path = paths.inventory_path(repo_id)
    stories_path = paths.stories_path(repo_id)
    if not inv_path.exists() or not stories_path.exists():
        missing = [str(p) for p in (inv_path, stories_path) if not p.exists()]
        raise FileNotFoundError(f"missing artifact(s): {missing}")

    inventory = Inventory.model_validate_json(inv_path.read_text())
    stories = Stories.model_validate_json(stories_path.read_text())
    lang_by_module = {m.id: m.language for m in inventory.modules}
    backlog = schedule(stories, language_by_module=lang_by_module)

    out = paths.backlog_path(repo_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(backlog.model_dump_json(indent=2), encoding="utf-8")
    return backlog
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_discovery_workflow.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/discovery/workflow.py tests/test_discovery_workflow.py
git commit -m "feat(discovery): workflow runner with hash-based caching and self-heal"
```

---

## Task 14: FastAPI endpoints — `/discover`, `/plan`, `/approve/backlog/{repo_id}`, `GET /discover/{repo_id}`

**Files:**
- Modify: `agent_harness/orchestrator/api.py`
- Test: `tests/test_discovery_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_api.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from agent_harness.orchestrator import api as api_mod
    api_mod._pipeline = None  # disable real pipeline init
    api_mod._ado = None
    return TestClient(api_mod.app)


def test_discover_400_on_missing_path(client):
    resp = client.post("/discover", json={"repo_id": "synth", "repo_path": "/no/such/dir"})
    assert resp.status_code == 404


def test_discover_invokes_workflow(client, tmp_path):
    repo_root = tmp_path / "synth"
    repo_root.mkdir()
    fake_result = {"status": "ok", "stages": [], "artifacts": {}}
    with patch("agent_harness.discovery.workflow.run_discovery",
               new=AsyncMock(return_value=fake_result)):
        resp = client.post("/discover", json={"repo_id": "synth",
                                              "repo_path": str(repo_root)})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_plan_409_when_no_discovery(client):
    resp = client.post("/plan", json={"repo_id": "missing"})
    assert resp.status_code == 409


def test_approve_backlog_flips_flag(client, tmp_path, monkeypatch):
    from agent_harness.persistence.repository import MigrationRepository
    db = tmp_path / "test.db"
    monkeypatch.setattr(
        "agent_harness.orchestrator.api._discovery_repo",
        MigrationRepository(db_path=db),
        raising=False,
    )
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.initialize()
    api_mod._discovery_repo.create_discovery_run("synth")

    resp = client.post("/approve/backlog/synth",
                       json={"approver": "alice", "comment": "lgtm"})
    assert resp.status_code == 200
    assert api_mod._discovery_repo.is_backlog_approved("synth")


def test_get_discover_returns_status(client, tmp_path, monkeypatch):
    from agent_harness.persistence.repository import MigrationRepository
    db = tmp_path / "test.db"
    monkeypatch.setattr(
        "agent_harness.orchestrator.api._discovery_repo",
        MigrationRepository(db_path=db),
        raising=False,
    )
    from agent_harness.orchestrator import api as api_mod
    api_mod._discovery_repo.initialize()
    api_mod._discovery_repo.create_discovery_run("synth")
    resp = client.get("/discover/synth")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repo_id"] == "synth"
    assert body["approved"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery_api.py -v`
Expected: 404 from `/discover` route etc.

- [ ] **Step 3: Add models + endpoints to `api.py`**

Add near the top, after the existing imports:

```python
from agent_harness.discovery import workflow as discovery_workflow
from agent_harness.discovery import paths as discovery_paths
from agent_harness.persistence.repository import MigrationRepository
```

Add module-level singleton:

```python
_discovery_repo: MigrationRepository = MigrationRepository()
```

Add to `lifespan` after pipeline init:

```python
    _discovery_repo.initialize()
```

Add new request/response models alongside existing ones:

```python
class DiscoverRequest(BaseModel):
    repo_id: str
    repo_path: str

class DiscoverResponse(BaseModel):
    status: str
    repo_id: str
    artifacts: dict = Field(default_factory=dict)
    stages: list[str] = Field(default_factory=list)
    message: str = ""

class PlanRequest(BaseModel):
    repo_id: str

class PlanResponse(BaseModel):
    repo_id: str
    backlog: list[dict]
    approved: bool

class ApproveRequest(BaseModel):
    approver: str
    comment: str = ""

class DiscoveryStatusResponse(BaseModel):
    repo_id: str
    created_at: str | None = None
    updated_at: str | None = None
    approved: bool = False
    approver: str | None = None
    artifacts: dict = Field(default_factory=dict)
```

Add endpoints:

```python
@app.post("/discover", response_model=DiscoverResponse)
async def discover(req: DiscoverRequest):
    if not os.path.isdir(req.repo_path):
        raise HTTPException(404, f"repo_path not found: {req.repo_path}")
    try:
        result = await discovery_workflow.run_discovery(
            repo_id=req.repo_id, repo_path=req.repo_path, repo=_discovery_repo,
        )
    except RuntimeError as e:
        return DiscoverResponse(status="blocked", repo_id=req.repo_id, message=str(e))
    return DiscoverResponse(
        status=result["status"], repo_id=req.repo_id,
        artifacts=result.get("artifacts", {}), stages=result.get("stages", []),
    )


@app.post("/plan", response_model=PlanResponse)
async def plan(req: PlanRequest):
    try:
        backlog = await discovery_workflow.run_planning(req.repo_id, _discovery_repo)
    except FileNotFoundError as e:
        raise HTTPException(409, str(e))
    return PlanResponse(
        repo_id=req.repo_id,
        backlog=[item.model_dump() for item in backlog.items],
        approved=_discovery_repo.is_backlog_approved(req.repo_id),
    )


@app.post("/approve/backlog/{repo_id}")
async def approve_backlog(repo_id: str, req: ApproveRequest):
    run = _discovery_repo.get_discovery_run(repo_id)
    if run is None:
        raise HTTPException(404, f"no discovery run for repo_id={repo_id}")
    _discovery_repo.approve_backlog(repo_id, approver=req.approver, comment=req.comment)
    return {"repo_id": repo_id, "approved": True}


@app.get("/discover/{repo_id}", response_model=DiscoveryStatusResponse)
async def get_discover(repo_id: str):
    run = _discovery_repo.get_discovery_run(repo_id)
    if run is None:
        raise HTTPException(404, f"no discovery run for repo_id={repo_id}")
    artifacts = {}
    for name, p in [
        ("inventory", discovery_paths.inventory_path(repo_id)),
        ("graph", discovery_paths.graph_path(repo_id)),
        ("stories", discovery_paths.stories_path(repo_id)),
        ("backlog", discovery_paths.backlog_path(repo_id)),
    ]:
        if p.exists():
            artifacts[name] = str(p)
    return DiscoveryStatusResponse(
        repo_id=repo_id,
        created_at=run.get("created_at"),
        updated_at=run.get("updated_at"),
        approved=bool(run.get("approved")),
        approver=run.get("approver"),
        artifacts=artifacts,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_discovery_api.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/orchestrator/api.py tests/test_discovery_api.py
git commit -m "feat(orchestrator): /discover, /plan, /approve, GET /discover endpoints"
```

---

## Task 15: End-to-end integration test on the synthetic 3-module fixture

**Files:**
- Test: `tests/test_discovery_e2e.py`

This test exercises the full pipeline with mocked LLM calls (canned JSON for each agent). All deterministic critics run for real.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_e2e.py
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.discovery.workflow import run_discovery, run_planning
from agent_harness.discovery.artifacts import (
    Inventory, ModuleRecord, Stories, Story, Epic, AcceptanceCriterion,
)
from agent_harness.discovery import paths
from agent_harness.persistence.repository import MigrationRepository

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_repo"


@pytest.mark.asyncio
async def test_e2e_synthetic_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = MigrationRepository(db_path=tmp_path / "e2e.db")
    repo.initialize()

    # Canned scanner output: matches FIXTURE.
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

    # Canned BRD body shared across modules — must include required sections AND
    # reference each AWS resource the module touches.
    def _brd_body(refs: list[str]) -> str:
        side = "\n".join(f"- writes/reads {r}" for r in refs)
        return (
            "## Purpose\nx\n\n## Triggers\nx\n\n## Inputs\nx\n\n## Outputs\nx\n\n"
            "## Business Rules\n- r\n\n"
            f"## Side Effects\n{side}\n\n"
            "## Error Paths\n- e\n\n## Non-Functionals\n- n\n\n## PII/Compliance\n- n\n"
        )

    brd_canned = {
        "orders": _brd_body(["dynamodb_table:Orders", "sqs_queue:payments-queue"]),
        "payments": _brd_body(["dynamodb_table:Orders", "dynamodb_table:Payments",
                               "sns_topic:payment-events"]),
        "notifications": _brd_body(["secrets_manager_secret:webhook/url"]),
    }

    def _design_body(refs: list[str]) -> str:
        sm = "\n".join(f"- {r} → Azure target" for r in refs)
        return (
            "## Function Plan\nFlex\n\n## Trigger Bindings\n- HTTP\n\n"
            f"## State Mapping\n{sm}\n\n## Secrets\n- KV\n\n"
            "## Identity\n- MI\n\n## IaC\n- Bicep\n\n## Observability\n- AI\n"
        )

    design_canned = {
        "orders": _design_body(["dynamodb_table:Orders", "sqs_queue:payments-queue"]),
        "payments": _design_body(["dynamodb_table:Orders", "dynamodb_table:Payments",
                                  "sns_topic:payment-events"]),
        "notifications": _design_body(["secrets_manager_secret:webhook/url"]),
    }

    stories_canned = Stories(
        epics=[
            Epic(id="E1", module_id="orders", title="Migrate orders", story_ids=["S1"]),
            Epic(id="E2", module_id="payments", title="Migrate payments", story_ids=["S2"]),
            Epic(id="E3", module_id="notifications", title="Migrate notifications",
                 story_ids=["S3"]),
        ],
        stories=[
            Story(id="S1", epic_id="E1", title="orders fn", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=[], blocks=["S2"], estimate="M"),
            Story(id="S2", epic_id="E2", title="payments fn", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S1"], blocks=["S3"], estimate="M"),
            Story(id="S3", epic_id="E3", title="notifications fn", description="d",
                  acceptance_criteria=[AcceptanceCriterion(text="ac")],
                  depends_on=["S2"], blocks=[], estimate="M"),
        ],
    ).model_dump_json()

    async def _module_brd_side_effect(message: str) -> str:
        for mid in brd_canned:
            if f"`{mid}`" in message:
                return brd_canned[mid]
        return "## Business Rules\n- r\n## Error Paths\n- e\n## Side Effects\n- none\n"

    async def _module_design_side_effect(message: str) -> str:
        for mid in design_canned:
            if f"`{mid}`" in message:
                return design_canned[mid]
        return "## State Mapping\n- none\n"

    with patch("agent_harness.discovery.repo_scanner._run_agent",
               new=AsyncMock(return_value=inv_json)), \
         patch("agent_harness.discovery.dependency_grapher._run_agent",
               new=AsyncMock(return_value="[]")), \
         patch("agent_harness.discovery.brd_extractor._run_module_agent",
               side_effect=_module_brd_side_effect), \
         patch("agent_harness.discovery.brd_extractor._run_system_agent",
               new=AsyncMock(return_value="# System BRD\nok")), \
         patch("agent_harness.discovery.architect._run_module_agent",
               side_effect=_module_design_side_effect), \
         patch("agent_harness.discovery.architect._run_system_agent",
               new=AsyncMock(return_value="# System Design\nok")), \
         patch("agent_harness.discovery.story_decomposer._run_agent",
               new=AsyncMock(return_value=stories_canned)):
        result = await run_discovery(repo_id="synth", repo_path=str(FIXTURE), repo=repo)

    assert result["status"] == "ok"

    # Graph assertions (deterministic).
    from agent_harness.discovery.tools.graph_io import load
    graph = load(paths.graph_path("synth"))
    edges = {(e.src, e.dst, e.kind) for e in graph.edges}
    assert ("orders", "dynamodb_table:Orders", "writes") in edges
    assert ("orders", "sqs_queue:payments-queue", "produces") in edges
    assert ("payments", "dynamodb_table:Payments", "writes") in edges
    assert ("payments", "sns_topic:payment-events", "produces") in edges
    assert ("notifications", "secrets_manager_secret:webhook/url", "reads") in edges
    # Cross-module imports via shared.util do NOT yield module→module edges
    # because `shared` is not in inventory — verify the head-segment heuristic.
    assert not any(e[1] == "shared" for e in edges)

    # Backlog assertions.
    backlog = await run_planning(repo_id="synth", repo=repo)
    waves = [item.wave for item in backlog.items]
    # S1 → S2 → S3 produces strictly increasing waves.
    assert waves == sorted(waves)
    assert max(waves) - min(waves) == 2
    # backlog.json is on disk.
    assert paths.backlog_path("synth").exists()
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_discovery_e2e.py -v`
Expected: 1 PASS.

- [ ] **Step 3: Run the entire suite to verify no regressions**

Run: `pytest tests/ -v`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_discovery_e2e.py
git commit -m "test(discovery): end-to-end mocked-LLM test on synthetic repo"
```

---

## Task 16: Public re-exports + README pointer

**Files:**
- Modify: `agent_harness/discovery/__init__.py`
- Modify: `README.md` (add a single section linking to spec + new endpoints)

- [ ] **Step 1: Update `__init__.py`**

```python
# agent_harness/discovery/__init__.py
"""Discovery & Planning subpackage.

Public entry points:
- run_discovery(repo_id, repo_path, repo) — runs the 5 LLM stages.
- run_planning(repo_id, repo) — runs WaveScheduler over stored artifacts.

See docs/superpowers/specs/2026-04-14-discovery-planning-layer-design.md.
"""
from .workflow import run_discovery, run_planning

__all__ = ["run_discovery", "run_planning"]
```

- [ ] **Step 2: Append a section to `README.md`**

Add after the existing endpoints section:

```markdown
## Discovery & Planning Endpoints

For multi-module repos, run discovery first to produce a wave-ordered backlog:

- `POST /discover {repo_id, repo_path}` — inventory → graph → BRDs → designs → stories.
- `POST /plan {repo_id}` — runs WaveScheduler; returns ordered backlog (unapproved).
- `POST /approve/backlog/{repo_id} {approver, comment}` — gates downstream `/migrate` fan-out.
- `GET /discover/{repo_id}` — current status, artifact paths, approval state.

Artifacts land under `discovery/<repo_id>/`. See
`docs/superpowers/specs/2026-04-14-discovery-planning-layer-design.md`.
```

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add agent_harness/discovery/__init__.py README.md
git commit -m "docs(discovery): expose public entry points and document endpoints"
```

---

## Self-Review Notes

- **Spec coverage:** Tasks 1–16 cover §3 (placement & DAG), §4 (every component incl. critics), §5 (data contracts), §6 (control flow + endpoints + cache loop), §7 (persistence tables), §8 (error handling — `blocked.md`, 409, cycle errors, approval gate), §9 (unit + integration + e2e), and §10 (migration order is preserved).
- **Approval gate enforcement (§6.3):** v1 stores the approval flag and exposes `is_backlog_approved`. Sub-project B's `/migrate-repo` will read it; this plan does not modify `/migrate` itself, which matches the spec's "Out of scope" §2.
- **Open questions (§11):** Tree-sitter is replaced by stdlib `ast` in Task 3 (note in module docstring). Critic prompt versioning is handled via `PROMPT_VERSION` constant in `workflow.py:hash_inputs` — bumping it invalidates every cache row.
- **Type consistency:** `BacklogItem` superset is asserted in Task 1 against `MigrationRequest`. `EdgeKind` and `ResourceKind` literals match between `artifacts.py`, `aws_sdk_patterns.py`, and the prompts.
