# Discovery & Planning Layer — Design Spec

**Date:** 2026-04-14
**Status:** Draft — pending review
**Target repo:** `ms-agent-harness`
**Framework:** Microsoft Agent Framework (`agent-framework` + `agent_framework_foundry`)

---

## 1. Context

The existing `ms-agent-harness` migrates a **single** AWS Lambda module to Azure Functions via a 7-gate pipeline (Analyzer → Contract → self-heal Coder/Tester → Reviewer → Security). It takes a `module` name as input and assumes discovery and planning have already happened.

For real client repos (multi-language, multi-module, cross-module dependencies, shared AWS resources) we need an upstream layer that:

1. Inventories the repo.
2. Builds a cross-module + AWS-resource dependency graph.
3. Extracts a BRD from source.
4. Produces an Azure target design.
5. Decomposes work into epics/stories with dependencies.
6. Schedules migration waves respecting the dep graph.
7. Emits a backlog the existing `/migrate` endpoint can consume, wave by wave.

This spec defines that layer. It is **sub-project A** of a 4-part decomposition (B: multi-module orchestration upgrade; C: evaluation framework; D: harness hardening).

## 2. Scope

### In scope (v1)

- Python Lambdas only. Multi-module. Multi-file per module.
- New subpackage `agent_harness/discovery/` inside `ms-agent-harness`.
- 6-node MAF `Workflow` DAG of specialist agents + deterministic scheduler.
- Typed artifacts written to disk at every stage.
- Critic agent per stage + self-heal loop (≤3 attempts), mirroring existing `pipeline.py`.
- Three new FastAPI endpoints on the existing orchestrator app.
- SQLite-backed resume/caching via input-hash per stage.
- Human approval gate on final backlog.
- Unit + mocked-LLM integration tests mirroring existing `tests/` layout.

### Out of scope (v1)

- Non-Python languages (Java, Node, C#) — additive in v1.1 via per-language tree-sitter adapters and prompt tags.
- Auto-fanout from approved backlog into `/migrate` execution — belongs to sub-project B.
- Cross-module integration tests post-migration — sub-project B.
- Full evaluation framework (golden sets, regression benchmarks, LLM-as-judge rubrics beyond critics) — sub-project C.
- Agent-as-tool hybrid pattern — defer until a concrete use case emerges.
- Extraction of Codex-OSS patterns (plan files, AGENTS.md, richer tool surface) — sub-project D.

## 3. Architecture

### 3.1 Placement

```
ms-agent-harness/
└── agent_harness/
    ├── base.py                  [reused] agent factory
    ├── config.py                [reused] model routing, speed profiles
    ├── pipeline.py              [reused] migration pipeline (downstream consumer)
    ├── persistence/             [reused + extended] SQLite repo
    ├── orchestrator/api.py      [extended] + /discover /plan /approve
    └── discovery/               [NEW]
        ├── workflow.py          MAF Workflow: 6-node DAG + resume orchestration
        ├── repo_scanner.py      Agent: inventory modules
        ├── dependency_grapher.py Agent: code + AWS-resource graph
        ├── brd_extractor.py     Agent: per-module + system BRD
        ├── architect.py         Agent: Azure target design
        ├── story_decomposer.py  Agent: epics/stories w/ deps
        ├── wave_scheduler.py    Deterministic: topo-sort → waves
        ├── critics/
        │   ├── graph_critic.py
        │   ├── brd_critic.py
        │   ├── design_critic.py
        │   └── story_critic.py
        ├── tools/
        │   ├── tree_sitter_py.py
        │   ├── aws_sdk_patterns.py
        │   └── graph_io.py
        ├── artifacts.py         Pydantic schemas for all artifacts
        └── prompts/             One .md per agent + critic
```

### 3.2 Reuse of existing infrastructure

- `base.create_agent(role, tools)` — same factory; new roles register prompts in `discovery/prompts/`.
- `base.run_with_retry` — rate-limit + context-length handling.
- `config.Settings.model_for_role` — extended to cover new roles (defaults: scanner/grapher/scheduler/critic → `gpt-4o-mini`; brd/architect/decomposer → `gpt-4o`).
- `persistence/repository.py` — extended with `discovery_runs` and `discovery_stage_cache` tables.
- `state_manager.StateManager` — learned rules emitted by discovery critics feed the existing `learned-rules.md` mechanism; migration agents downstream inherit them.
- Prompt loader — `quality-principles.md` + `learned-rules.md` + `program.md` injection applies to discovery agents too.

### 3.3 DAG

```
RepoScanner ─► DependencyGrapher ─► BRDExtractor ─► Architect ─► StoryDecomposer ─► WaveScheduler
   │                  │                  │              │              │                  │
   └─► inventory.json │                  │              │              │                  │
                      └─► graph.json     │              │              │                  │
                                         └─► brd/*.md   │              │                  │
                                                        └─► design/*.md │                  │
                                                                        └─► stories.json   │
                                                                                           └─► backlog.json
```

Each edge is **artifact-on-disk**, not in-memory chat. The workflow reads the predecessor artifact(s) from disk and includes them in the successor agent's prompt. This is what makes the DAG resumable, cacheable, and independently evaluable.

## 4. Components

### 4.1 RepoScanner

- **Role:** Inventory modules in a repo.
- **Tools:** `read_file`, `list_directory`, `search_files` (existing, read-only).
- **Output:** `discovery/<repo_id>/inventory.json`
  - `modules: [{id, path, language, handler_entrypoint, loc, config_files}]`
  - `repo_meta: {root_path, total_files, total_loc, discovered_at}`
- **Critic:** None (deterministic sanity check: every listed `handler_entrypoint` exists and is readable; language matches file extension).

### 4.2 DependencyGrapher

- **Role:** Build typed graph of cross-module code dependencies and shared AWS resources.
- **Tools:** `tree_sitter_py.parse_imports`, `tree_sitter_py.extract_calls`, `aws_sdk_patterns.resolve` (boto3 call → resource kind + name), `graph_io.add_node`, `graph_io.add_edge`.
- **Output:** `graph.json`
  - Nodes: `{id, kind: "module"|"aws_resource", attrs}` (resource kinds: `dynamodb_table`, `s3_bucket`, `sqs_queue`, `sns_topic`, `kinesis_stream`, `secrets_manager_secret`, `lambda_function`).
  - Edges: `{src, dst, kind: "imports"|"reads"|"writes"|"produces"|"consumes"|"invokes"|"shares_db"}`.
- **Approach:** Deterministic-first. Tree-sitter extracts imports and `boto3`/`aioboto3` call sites; SDK-pattern library resolves them to resource kinds. LLM is invoked only to resolve ambiguous cases (dynamic resource names, indirect client creation) flagged by the tool layer. Keeps eval tractable and cost low.
- **Critic (`graph_critic`):** Every `boto3`/`aioboto3` call site found by a ground-truth scan of source must have a corresponding edge. Every import between modules in inventory must have an `imports` edge. Failures produce a structured report that feeds back into the next attempt.

### 4.3 BRDExtractor

- **Role:** Extract Business Requirements per module and a system-level rollup.
- **Inputs:** `inventory.json`, `graph.json`, module source.
- **Output:**
  - `brd/<module_id>.md` — purpose, triggers, inputs, outputs, business rules, side effects, error paths, non-functionals (latency, idempotency, ordering guarantees), PII/compliance notes.
  - `brd/_system.md` — cross-module workflows, shared invariants.
- **Critic (`brd_critic`):** Every public handler in `inventory.json` has a BRD. Every BRD has non-empty `business_rules` and `error_paths` sections. Every shared AWS resource in `graph.json` is referenced by at least one BRD's side-effects section.

### 4.4 Architect

- **Role:** Produce target Azure design per module and system-wide.
- **Inputs:** BRDs + graph.
- **Output:**
  - `design/<module_id>.md` — target Functions plan (Consumption/Premium/Flex), trigger binding mapping (API Gateway → HTTP trigger; SQS → Service Bus queue trigger; S3 → Blob trigger or Event Grid; DynamoDB Streams → Cosmos DB change feed; EventBridge → Event Grid; Kinesis → Event Hubs), state-store mapping (DynamoDB → Cosmos DB NoSQL; RDS Postgres → Azure DB for PostgreSQL), secrets (Secrets Manager → Key Vault), identity (IAM role → Managed Identity), IaC target (Bicep), observability mapping (CloudWatch → App Insights).
  - `design/_system.md` — system-level decisions: strangler-fig seams (which modules migrate first), anti-corruption layers (where Azure-side code calls still-AWS dependencies), shared resource migration ordering (DB before consumers).
- **Critic (`design_critic`):** Every AWS resource kind referenced in any BRD has a target Azure mapping in the relevant design doc. Every trigger type in the module's BRD has a binding decision. Strangler seams are consistent with `graph.json` edges.

### 4.5 StoryDecomposer

- **Role:** Turn BRDs + designs into epics and user stories with explicit dependency tags.
- **Output:** `stories.json`
  - `epics: [{id, module_id, title, stories: [...]}]`
  - `stories: [{id, epic_id, title, description, acceptance_criteria: [...], depends_on: [story_id|resource_id], blocks: [...], estimate: S|M|L}]`
  - Dependency edges reflect both code-level (module A imports module B) and resource-level (store must exist before consumer) constraints.
- **Critic (`story_critic`):** Every story has ≥1 acceptance criterion. Every `depends_on` id exists. Every module in `inventory.json` has ≥1 epic. Dependency subgraph is acyclic.

### 4.6 WaveScheduler

- **Role:** Topologically sort stories into ordered migration waves.
- **Type:** Deterministic Python module, not an agent.
- **Inputs:** `stories.json`, `graph.json`.
- **Output:** `backlog.json`
  - Ordered list. Each item matches the shape of the existing `/migrate` request body (`module`, `language`, `work_item_id`, `title`, `description`, `acceptance_criteria`) plus a new field `wave: int`.
  - Waves = levels of the story DAG's topological layering.
- **Validation:** Cycle detection is a hard error with a listed cycle. No LLM involved.

### 4.7 Critic pattern

All four critics share the same shape (created via `base.create_agent(role='critic-*')`, read-only tools): input = the artifact + ground-truth scan of predecessors; output = JSON `{verdict: "PASS"|"FAIL", reasons: [...], suggestions: [...]}`. On FAIL, reasons are injected into the producing agent's next-attempt prompt. Mirrors the self-heal loop in `pipeline.py:130-164`.

## 5. Data contracts

All artifacts are Pydantic models in `discovery/artifacts.py`. `backlog.json` items are a strict superset of the schema already accepted by `orchestrator/api.py`'s `/migrate` endpoint, so sub-project B can consume without translation.

Key models (sketch):
- `Inventory`, `ModuleRecord`
- `DependencyGraph`, `GraphNode`, `GraphEdge`
- `BRD` (system-level), `ModuleBRD`
- `SystemDesign`, `ModuleDesign`
- `Epic`, `Story`, `AcceptanceCriterion`
- `BacklogItem` (extends the existing migrate-request schema with `wave: int`)
- `CriticReport`

## 6. Control flow

### 6.1 Endpoints

- `POST /discover {repo_path, repo_id}` — runs the 5 LLM stages (RepoScanner → Grapher → BRD → Architect → Stories). Returns stage statuses, artifact paths, and any critic reports. Synchronous in v1; can be made async later.
- `POST /plan {repo_id}` — runs WaveScheduler on stored artifacts. Returns `backlog.json` and `{approved: false}`.
- `POST /approve/backlog/{repo_id} {approver, comment}` — flips the `approved` flag in `discovery_runs`.
- `GET /discover/{repo_id}` — returns current stage statuses, cached artifacts, and approval state.

### 6.2 Per-stage execution

```
for stage in [scanner, grapher, brd, architect, stories]:
    input_hash = hash(predecessor_artifacts + prompt_version)
    if repo.stage_cache_hit(repo_id, stage.name, input_hash):
        continue
    for attempt in 1..3:
        result = await stage.run(inputs)
        critic_report = await stage.critic(result, ground_truth)
        if critic_report.verdict == "PASS":
            write_artifact(result)
            repo.cache_stage(repo_id, stage.name, input_hash)
            break
        inject(critic_report.reasons, into=stage.next_prompt)
    else:
        write_blocked_md(stage, critic_report)
        return WorkflowResult(status="blocked", stage=stage.name)
```

### 6.3 Approval gate (hard)

Sub-project B's future `/migrate-repo` endpoint will refuse to fan out migrations unless `discovery_runs.approved = true` for that `repo_id`. Enforced at the persistence layer, not just in the API handler.

## 7. Persistence

Two new SQLite tables (via `persistence/repository.py` extensions):

- `discovery_runs(repo_id PK, created_at, updated_at, approved BOOL, approver, approval_comment, approved_at)`
- `discovery_stage_cache(repo_id, stage_name, input_hash, artifact_path, created_at, PK(repo_id, stage_name))`

Cache key is `(repo_id, stage_name)`; value includes `input_hash` so hash mismatch triggers re-run. Artifacts on disk are the source of truth; the cache row just says "this artifact is current for these inputs."

## 8. Error handling

- **Transient LLM errors** → existing `base.run_with_retry` (exponential backoff on 429; context-length truncation retry).
- **Critic FAIL** → self-heal up to 3 attempts, injecting critic reasons. Mirrors `pipeline.py`.
- **3× FAIL** → stage writes `discovery/<repo_id>/<stage>/blocked.md` with the critic's last report, workflow halts, returns `status=blocked, stage=<name>`. Human edits prompts/inputs and re-triggers; cache skips prior-passing stages.
- **Cycle in story dep graph** → `wave_scheduler` returns a deterministic error naming the cycle. No retry.
- **Missing prerequisite artifact** (e.g., `POST /plan` before `POST /discover`) → 409 Conflict with the missing stage listed.
- **Approval required** → downstream consumers (sub-project B) check the persistence-layer flag; no soft checks in the handler alone.

## 9. Testing

Mirrors the existing `tests/` layout.

- **Unit (no LLM, free):**
  - `tree_sitter_py`: import extraction, call extraction on fixture files.
  - `aws_sdk_patterns`: boto3 call → resource kind on a catalog of call patterns.
  - `graph_io`: add/lookup/serialize.
  - `wave_scheduler`: topo-sort correctness, cycle detection, layering.
  - Pydantic contract tests: every artifact model serializes/deserializes round-trip; `BacklogItem` is a superset of `/migrate`'s request model.
- **Integration (mocked LLM, free):**
  - One test per LLM stage asserting artifact shape and critic-pass.
  - End-to-end test on a 3-module synthetic fixture repo with hand-authored `boto3` calls producing a known dependency structure. Assertions:
    - `graph.json` includes exactly the expected nodes and edges.
    - `backlog.json` order respects topological layering.
    - `depends_on` is consistent with `graph.json`.
- **Eval seed (minimal; full suite = sub-project C):**
  - Golden-repo fixture with hand-written expected `graph.json` and `stories.json`. Score = exact-match on graph edges + story-count + dependency-edge set.

## 10. Migration plan (how this ships)

1. Scaffolding: `discovery/` subpackage, Pydantic artifacts, SQLite table migrations, prompt files.
2. Tools layer: `tree_sitter_py`, `aws_sdk_patterns`, `graph_io` with unit tests.
3. `WaveScheduler` (deterministic, easiest to land and test).
4. `RepoScanner` + deterministic sanity check.
5. `DependencyGrapher` + `graph_critic`.
6. `BRDExtractor` + `brd_critic`.
7. `Architect` + `design_critic`.
8. `StoryDecomposer` + `story_critic`.
9. `Workflow` wiring + resume/caching.
10. FastAPI endpoints + approval gate.
11. Integration test on the 3-module synthetic fixture.

Each step is independently testable; order minimizes blocking.

## 11. Open questions (none blocking)

- Tree-sitter grammar distribution: vendor or install-time download? (Leaning: install-time via `tree-sitter-languages` package to keep the repo small.)
- Should critics themselves be version-pinned prompts? (Leaning: yes — include `prompt_version` in the stage input-hash so prompt edits invalidate cache.)

Both decisions will be resolved during implementation; neither blocks the design.

---

**Next step:** user reviews this spec, then implementation plan via `writing-plans`.
