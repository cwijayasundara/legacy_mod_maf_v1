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
