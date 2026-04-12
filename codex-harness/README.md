# Codex Harness — AWS Lambda to Azure Functions Migration

Codex-native migration framework with 5 TOML-configured agents, 7 Node.js enforcement hooks, and a FastAPI orchestrator. Ported from the [Claude Harness Engine](https://github.com/cwijayasundara/claude_harness_eng_v1).

## Structure

```
codex-harness/
│
├── .codex/                              ← CODEX PACKAGE (auto-loaded by Codex)
│   ├── agents/                          5 TOML agent definitions
│   │   ├── analyzer.toml               Dependency analysis (o4, read-only)
│   │   ├── coder.toml                  TDD migration (codex-mini, write)
│   │   ├── tester.toml                 3-layer evaluation (o4-mini, write)
│   │   ├── reviewer.toml              8-point quality gate (o4, read-only)
│   │   └── security-reviewer.toml     OWASP top 10 scanner (o4, read-only)
│   ├── config.toml                     Models, hooks, protected paths
│   ├── AGENTS.md                       Root migration guidance
│   ├── quality-principles.md           6 code quality rules (TDD, typing, decomposition)
│   ├── architecture.md                 Layered dependency rules
│   └── scripts/                        Node.js CLI runners + enforcement hooks
│       ├── migrate-module.js           Single module migration
│       ├── migrate-batch.js            Parallel DAG-based batch
│       ├── setup.js                    One-time environment setup
│       └── hooks/                      7 enforcement hooks (architecture, length,
│           ├── check-architecture.js     secrets, lint, types, pre-commit)
│           ├── check-file-length.js
│           ├── check-function-length.js
│           ├── detect-secrets.js
│           ├── post-task-lint.js
│           ├── pre-commit-gate.js
│           └── typecheck.js
│
├── harness/                             ← HARNESS PACKAGE (REST API)
│   └── orchestrator/
│       ├── api.py                      FastAPI: /migrate, /status, /health
│       ├── codex_runner.py             Async Codex CLI wrapper
│       ├── state_manager.py            State persistence (local + Azure Blob)
│       ├── ado_client.py               ADO REST (PRs, work items)
│       └── README.md                   Full API documentation
│
├── example/                             ← SAMPLE LAMBDA
│   ├── lambda/handler.py               Order processor (DynamoDB + S3 + SQS)
│   └── README.md                       Step-by-step usage guide
│
├── config/                              ← CONFIGURATION
│   ├── program.md                       Human steering (edit mid-run)
│   ├── templates/                       Sprint contract + failure report schemas
│   └── state/                           Learned rules, progress, coverage baseline
│
├── migrated_code/                       ← OUTPUT (generated at runtime)
├── tests/                               ← UNIT TESTS
├── requirements.txt                     Python dependencies
└── Dockerfile                           Container image (Python + Node.js + Codex CLI)
```

## Prerequisites

```bash
# Node.js 18+ (required for Codex CLI and hooks)
node --version

# Python 3.11+ (required for orchestrator API)
python3 --version

# Codex CLI
npm install -g @openai/codex
```

## Setup

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Set API key — choose ONE method:

#   Method A: Environment variable
export OPENAI_API_KEY=sk-...

#   Method B: .env file (create in parent directory)
echo "OPENAI_API_KEY=sk-..." > ../.env

#   Method C: Codex ChatGPT login (no API key needed)
codex login

# 3. Copy example Lambda into place
mkdir -p src/lambda/order-processor
cp example/lambda/* src/lambda/order-processor/
```

## Running the Migration

### Option A: Via Codex CLI (direct)

```bash
# Single module
node .codex/scripts/migrate-module.js order-processor python WI-1001

# Batch (parallel, reads from .codex/scripts/modules.tsv)
node .codex/scripts/migrate-batch.js --parallel 3
```

### Option B: Via REST API

```bash
# Start the orchestrator
uvicorn harness.orchestrator.api:app --host 0.0.0.0 --port 8000

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

# Health check
curl http://localhost:8000/health
```

### Option C: Via Docker

```bash
docker build -t codex-harness .
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -v $(pwd)/src/lambda:/app/codex-harness/src/lambda:ro \
  codex-harness

# Then use the API as in Option B
```

## What Happens During Migration

```
1. Analyzer agent (o4, read-only)
   → Reads Lambda source, maps AWS deps, scores complexity
   → Output: migration-analysis/{module}/analysis.md

2. Coder agent (codex-mini, write)
   → Proposes sprint contract (what PASS means)
   → TDD: writes tests first, then migrates code
   → Generates Bicep template
   → Output: src/azure-functions/{module}/, infrastructure/{module}/

3. Tester agent (o4-mini, write)
   → Finalizes sprint contract
   → 3-layer evaluation: unit → integration → contract
   → On failure: structured eval-failures.json → coder retries (up to 3x)
   → Output: migration-analysis/{module}/test-results.md

4. Reviewer agent (o4, read-only)
   → 8-point quality checklist
   → Output: migration-analysis/{module}/review.md (APPROVE/BLOCK)

5. Security reviewer agent (o4, read-only)
   → OWASP top 10 scan
   → Output: migration-analysis/{module}/security-review.md
```

## Engineering Scaffolding

Quality principles that teach agents to be good engineers:

| Principle | Enforcement |
|-----------|-------------|
| Small modules (300 line max) | `check-file-length.js` hook |
| Functions under 50 lines | `check-function-length.js` hook |
| Static typing (full hints) | `typecheck.js` hook (mypy/tsc) |
| Layered architecture | `check-architecture.js` hook |
| No secrets in code | `detect-secrets.js` hook |
| Tests + lint before commit | `pre-commit-gate.js` hook |
| TDD-first | Enforced in coder.toml instructions |
| Coverage ratcheting | state/coverage-baseline.txt (only goes up) |
| OWASP security scan | security-reviewer.toml agent |

## Running Tests

```bash
# Unit tests (no LLM needed)
pip install pytest pytest-cov pytest-asyncio httpx
pytest tests/ -v
```

## API Documentation

See `harness/orchestrator/README.md` for full endpoint docs, request/response schemas, and environment variables.

See `example/README.md` for a step-by-step walkthrough of migrating the sample Lambda.
