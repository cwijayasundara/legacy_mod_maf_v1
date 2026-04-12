# Codex Harness — AWS Lambda to Azure Functions Migration

Codex-native migration framework with 4 TOML-configured agents and a REST API. Ported from the [Claude Harness Engine](https://github.com/cwijayasundara/claude_harness_eng_v1).

## Structure

```
codex-harness/
│
├── .codex/                              ← CODEX PACKAGE (loaded by Codex automatically)
│   ├── agents/                          4 TOML agent definitions
│   │   ├── analyzer.toml               Dependency analysis (o4, read-only)
│   │   ├── coder.toml                  TDD migration (codex-mini, write)
│   │   ├── tester.toml                 3-layer evaluation (o4-mini, write)
│   │   └── reviewer.toml              8-point quality gate (o4, read-only)
│   ├── config.toml                     Models, hooks, protected paths
│   └── AGENTS.md                       Root migration guidance
│
├── .codex/                              (continued)
│   └── scripts/                        CLI runners + enforcement hooks
│       ├── migrate-module.js           Single module migration
│       ├── migrate-batch.js            Parallel DAG-based batch
│       └── hooks/                      Lint, secrets, pre-commit gates
│
├── harness/                             ← HARNESS PACKAGE (custom code)
│   └── orchestrator/                    REST API (FastAPI) + Codex runner + ADO client
│       ├── api.py                      /migrate, /status, /health
│       ├── codex_runner.py             Async Codex CLI wrapper
│       ├── state_manager.py            State persistence (local + Azure Blob)
│       ├── ado_client.py               ADO REST (PRs, work items)
│       └── README.md                   API trigger documentation
│
├── example/                             ← SAMPLE LAMBDA
│   ├── lambda/handler.py               Order processor (DynamoDB + S3 + SQS)
│   └── README.md                       Usage guide
│
├── migrated_code/                       ← OUTPUT (generated at runtime)
│
├── config/                              ← CONFIGURATION
│   ├── program.md                       Human steering
│   ├── templates/                       Sprint contract + failure report schemas
│   └── state/                           Learned rules, progress, coverage baseline
│
├── tests/                               ← TESTS
├── requirements.txt
└── Dockerfile
```

## Quick Start

```bash
# Install Codex CLI + Python deps
npm install -g @openai/codex
pip install -r requirements.txt

# Set API key (or use `codex login` for ChatGPT auth)
export OPENAI_API_KEY=sk-...

# Copy example Lambda into place
mkdir -p src/lambda/order-processor
cp example/lambda/* src/lambda/order-processor/

# Option A: Run via CLI
.codex/scripts/migrate-module.js order-processor python WI-DEMO

# Option B: Run via REST API
uvicorn harness.orchestrator.api:app --port 8000
curl -X POST http://localhost:8000/migrate/sync \
  -H "Content-Type: application/json" \
  -d '{"module": "order-processor", "language": "python"}'
```

See `harness/orchestrator/README.md` for full API documentation.
