# MS Agent Harness — AWS Lambda to Azure Functions Migration

Migration framework built on [Microsoft Agent Framework](https://pypi.org/project/agent-framework/) (`Agent` + `@tool` + `FoundryChatClient`). Four specialized agents with context engineering, large file handling, SQLite caching, and checkpoint/resume.

## Structure

```
ms-agent-harness/
│
├── agent_harness/                       ← THE PACKAGE
│   ├── base.py                          Agent factory (FoundryChatClient + Agent)
│   ├── pipeline.py                      Sequential orchestrator + self-healing
│   ├── config.py                        Speed profiles, model routing
│   ├── analyzer.py                      Dependency analysis + complexity scoring
│   ├── coder.py                         TDD migration (generator role)
│   ├── tester.py                        3-layer evaluation (evaluator role)
│   ├── reviewer.py                      8-point quality gate
│   ├── context/                         Chunker, compressor, token estimator, scorer
│   ├── tools/                           @tool: file ops, AST parsing, test runner
│   ├── persistence/                     SQLite cache + state manager
│   ├── prompts/                         System prompts per agent role
│   └── orchestrator/                    REST API (FastAPI) + ADO client
│
├── example/                             ← SAMPLE LAMBDA
│   ├── lambda/handler.py                Order processor (DynamoDB + S3 + SQS)
│   └── README.md                        Usage guide
│
├── migrated_code/                       ← OUTPUT (generated at runtime)
│   └── (populated by migration agents)
│
├── config/                              ← CONFIGURATION
│   ├── settings.yaml                    Models, speed profiles, rate limits
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
# Install
pip install -r requirements.txt

# Set API key
export OPENAI_API_KEY=sk-...
# Or add to .env file in parent directory

# Copy example Lambda into place
mkdir -p src/lambda/order-processor
cp example/lambda/* src/lambda/order-processor/

# Run via REST API
uvicorn agent_harness.orchestrator.api:app --port 8000
curl -X POST http://localhost:8000/migrate/sync \
  -H "Content-Type: application/json" \
  -d '{"module": "order-processor", "language": "python"}'
```

See `agent_harness/orchestrator/README.md` for full API documentation.
