# MS Agent Harness — AWS Lambda to Azure Functions Migration

Migration framework built on [Microsoft Agent Framework](https://pypi.org/project/agent-framework/) (`Agent` + `@tool` + `FoundryChatClient`). Five specialized Python agents with context engineering, large file handling, SQLite caching, quality enforcement, and security scanning.

## Structure

```
ms-agent-harness/
│
├── agent_harness/                       ← THE PACKAGE
│   ├── base.py                          Agent factory (FoundryChatClient + Agent)
│   ├── pipeline.py                      Sequential orchestrator + self-healing (7 gates)
│   ├── config.py                        Speed profiles, model routing
│   ├── analyzer.py                      Dependency analysis + complexity scoring
│   ├── coder.py                         TDD migration (generator role)
│   ├── tester.py                        3-layer evaluation (evaluator role)
│   ├── reviewer.py                      8-point quality gate
│   ├── security_reviewer.py             OWASP top 10 scanner (automated + LLM)
│   ├── context/                         Context Engineering
│   │   ├── chunker.py                   Semantic file splitting at AST boundaries
│   │   ├── compressor.py                Progressive compression (30% older history)
│   │   ├── token_estimator.py           Token budget: chars ÷ 3.0 × multiplier
│   │   └── complexity_scorer.py         Lambda complexity scoring (12 patterns)
│   ├── tools/                           @tool-decorated agent tools
│   │   ├── file_tools.py               Read, write, search, list
│   │   ├── ast_tools.py                Parse imports, extract functions, find AWS deps
│   │   └── test_runner.py              Run pytest/jest, measure coverage
│   ├── persistence/                     Caching + State
│   │   ├── repository.py               SQLite: analysis cache, chunk status, resume
│   │   └── state_manager.py            Learned rules, progress, coverage baseline
│   ├── quality/                         Quality Enforcement
│   │   ├── architecture_checker.py     Layered import enforcement (Python)
│   │   ├── code_quality.py             6 rules as checkable functions
│   │   └── security_scanner.py         OWASP regex patterns + severity
│   ├── prompts/                         System Prompts
│   │   ├── analyzer.md, coder.md, tester.md, reviewer.md
│   │   ├── security-reviewer.md
│   │   └── quality-principles.md        Injected into ALL agents
│   └── orchestrator/                    REST API
│       ├── api.py                       FastAPI: /migrate, /status, /health
│       ├── ado_client.py                ADO REST (PRs, work items)
│       └── README.md                    Full API documentation
│
├── example/                             ← SAMPLE LAMBDA
│   ├── lambda/handler.py                Order processor (DynamoDB + S3 + SQS)
│   └── README.md                        Step-by-step usage guide
│
├── config/                              ← CONFIGURATION
│   ├── settings.yaml                    Model deployments, speed profiles, rate limits
│   ├── program.md                       Human steering (edit mid-run)
│   ├── templates/                       Sprint contract + failure report schemas
│   └── state/                           Learned rules, progress, coverage baseline
│
├── migrated_code/                       ← OUTPUT (generated at runtime)
├── tests/                               ← UNIT + INTEGRATION TESTS
├── requirements.txt                     All Python dependencies
├── pyproject.toml                       pytest config
└── Dockerfile                           Pure Python container (~400MB)
```

## Prerequisites

```bash
# Python 3.11+
python3 --version

# pip (for installing dependencies)
pip --version
```

No Node.js required — everything runs in Python.

## Setup

```bash
# 1. Install all dependencies
pip install -r requirements.txt

# 2. Set credentials — choose ONE method:

#   Method A: Azure AI Foundry (production)
export FOUNDRY_PROJECT_ENDPOINT=https://your-project.services.ai.azure.com
export FOUNDRY_MODEL=gpt-4o

#   Method B: OpenAI directly (local dev)
export OPENAI_API_KEY=sk-...

#   Method C: .env file (create in parent directory)
echo "OPENAI_API_KEY=sk-..." > ../.env

# 3. Copy example Lambda into place
mkdir -p src/lambda/order-processor
cp example/lambda/* src/lambda/order-processor/
```

## Running the Migration

### Option A: Via REST API

```bash
# Start the orchestrator
uvicorn agent_harness.orchestrator.api:app --host 0.0.0.0 --port 8000

# Trigger migration (async — returns immediately)
curl -X POST http://localhost:8000/migrate \
  -H "Content-Type: application/json" \
  -d '{
    "module": "order-processor",
    "language": "python",
    "work_item_id": "WI-1001",
    "title": "Migrate order-processor to Azure Functions"
  }'

# Trigger migration (sync — blocks until complete, for demos)
curl -X POST http://localhost:8000/migrate/sync \
  -H "Content-Type: application/json" \
  -d '{"module": "order-processor", "language": "python"}'

# Check status
curl http://localhost:8000/status/order-processor

# List all migrations
curl http://localhost:8000/status

# Health check
curl http://localhost:8000/health
```

### Option B: Via Docker

```bash
docker build -t ms-agent-harness .
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -v $(pwd)/src/lambda:/app/ms-agent-harness/src/lambda:ro \
  ms-agent-harness

# Then use the API as in Option A
```

### Option C: Via Python directly

```python
import asyncio
from agent_harness.pipeline import MigrationPipeline

async def main():
    pipeline = MigrationPipeline(project_root=".")
    result = await pipeline.run(
        module="order-processor",
        language="python",
        work_item_id="WI-1001",
    )
    print(f"Status: {result.status}, Score: {result.review_score}")

asyncio.run(main())
```

## What Happens During Migration (7 Gates)

```
Gate 1: Analyzer agent (gpt-4o)
   → Reads Lambda source, maps AWS deps, scores complexity
   → Caches results in SQLite (skip on retry)
   → Output: migration-analysis/{module}/analysis.md

Gate 2: Sprint Contract Negotiation
   → Coder proposes contract (what PASS means)
   → Tester finalizes (adds/removes checks)
   → Contract is immutable after finalization

Gates 3-5: Self-Healing Migration Loop (up to 3 attempts)
   → Coder (gpt-4o-mini): TDD-first, writes tests then code
   → Tester (gpt-4o-mini): 3-layer evaluation (unit, integration, contract)
   → On failure: structured eval-failures.json feeds back to coder

Gate 6: Reviewer agent (gpt-4o)
   → 8-point quality checklist
   → Output: migration-analysis/{module}/review.md

Gate 7: Security Reviewer agent (gpt-4o)
   → Automated OWASP regex scan + LLM deep analysis
   → Output: migration-analysis/{module}/security-review.md
```

## Engineering Scaffolding

Quality principles injected into every agent's system prompt:

| Principle | Enforcement |
|-----------|-------------|
| Small modules (300 line max) | `quality/code_quality.py` check |
| Functions under 50 lines | `quality/code_quality.py` check |
| Static typing (full hints) | `quality/code_quality.py` check |
| Layered architecture | `quality/architecture_checker.py` |
| No secrets in code | `quality/security_scanner.py` |
| Explicit error handling | Prompt instruction + quality check |
| TDD-first | Enforced in pipeline sequence |
| Coverage ratcheting | `state/coverage-baseline.txt` (only goes up) |
| OWASP security scan | `security_reviewer.py` agent (Gate 7) |
| Learned rules | `state/learned-rules.md` (injected into all agents) |

## Running Tests

```bash
# Unit tests (no LLM needed, free)
pip install pytest pytest-cov pytest-asyncio
pytest tests/ -v --ignore=tests/test_integration.py

# Integration tests (mocked LLM, free)
pytest tests/test_integration.py -v

# All tests
pytest tests/ -v
```

## Configuration

Edit `config/settings.yaml` to change:
- **Model routing**: which model each agent uses
- **Speed profiles**: Turbo/Fast/Balanced/Thorough (token budgets, parallelism)
- **Rate limits**: tokens per minute, requests per minute
- **Quality thresholds**: coverage floor, reviewer confidence, max retries

Edit `config/program.md` to steer agents mid-run:
- Override max attempts per module
- Skip integration tests for specific modules
- Adjust confidence thresholds

## API Documentation

See `agent_harness/orchestrator/README.md` for full endpoint docs, request/response schemas, and environment variables.

See `example/README.md` for a step-by-step walkthrough.

## How It Differs From codex-harness

| Aspect | codex-harness | ms-agent-harness |
|--------|--------------|-----------------|
| Framework | Codex CLI (external binary) | MS Agent Framework (in-process) |
| Agents | TOML config files | Python classes with `Agent()` + `@tool` |
| Context engineering | Codex handles automatically | Custom: chunker, compressor, token estimator |
| Large files | Codex server-side compaction | Semantic chunking at AST boundaries |
| Caching | None (stateless per run) | SQLite: analysis cache, chunk status, resume |
| Quality enforcement | Node.js hooks (7 scripts) | Python functions in `quality/` package |
| Dependencies | Node.js + Codex CLI + Python | Pure Python |
| Container size | ~1.2GB | ~400MB |

## Discovery & Planning Endpoints

For multi-module repos, run discovery first to produce a wave-ordered backlog:

- `POST /discover {repo_id, repo_path}` — inventory → graph → BRDs → designs → stories.
- `POST /plan {repo_id}` — runs WaveScheduler; returns ordered backlog (unapproved).
- `POST /approve/backlog/{repo_id} {approver, comment}` — gates downstream `/migrate` fan-out.
- `GET /discover/{repo_id}` — current status, artifact paths, approval state.

Artifacts land under `discovery/<repo_id>/`. See
`docs/superpowers/specs/2026-04-14-discovery-planning-layer-design.md`.

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

## Per-repo and per-module agent context (AGENTS.md)

Drop an `AGENTS.md` at the root of the repo being migrated to give every
agent (discovery + migration) shared context — domain glossary, invariants,
forbidden/preferred patterns, Azure naming conventions. For module-specific
overrides, drop a second `AGENTS.md` inside the module's directory.

Injection order (later entries can override earlier ones):

1. Stage prompt (e.g. `prompts/coder.md`).
2. `prompts/quality-principles.md`.
3. `config/state/learned-rules.md`.
4. `config/program.md`.
5. `<repo_root>/AGENTS.md`.
6. `<module_path>/AGENTS.md` (migration only — discovery is repo-scoped).

See `templates/AGENTS.md.example` for the conventions.

## Additional agent tools

- `apply_patch(edits)` — atomic batch of search-replace edits. The coder uses
  this for incremental edits instead of whole-file rewrites. All edits in a
  batch are validated (each `old_string` matches `expected_count` times)
  before any file is touched; any failure aborts the batch.
- `validate_bicep(path)` — transpiles a Bicep file with `az bicep build
  --stdout`. Returns `VALID` / `INVALID: <stderr>` / `SKIPPED: <reason>`.
  Used by the reviewer and security_reviewer. When it returns `INVALID`,
  the reviewer is instructed never to APPROVE without regenerating.
