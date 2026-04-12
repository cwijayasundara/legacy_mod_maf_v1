# Sample: Migrating a Python Lambda to Azure Functions

This example shows how to use the Codex Harness to migrate `example/lambda/handler.py`
(a Python AWS Lambda with DynamoDB + S3 + SQS dependencies) to an Azure Function.

## The Source Lambda

```
example/lambda/
├── handler.py          Python Lambda handler
└── requirements.txt    boto3 (AWS SDK)
```

**What it does:** An order processing API (POST/GET /orders) that:
- Stores orders in DynamoDB
- Uploads receipts to S3
- Publishes notifications to SQS

## Prerequisites

```bash
# Install Codex CLI
npm install -g @openai/codex

# Set your API key (OpenAI or Azure OpenAI)
export OPENAI_API_KEY=sk-...

# For Azure OpenAI:
# export CODEX_API_BASE=https://YOUR_PROJECT.openai.azure.com/openai/v1
```

## Option A: Run via CLI

The scaffolding includes a CLI runner that invokes Codex with the 4-agent pipeline.

```bash
# From the codex-harness root:

# 1. Copy the sample Lambda into the expected location
mkdir -p src/lambda/order-processor
cp example/lambda/* src/lambda/order-processor/

# 2. Run the migration
.codex/scripts/migrate-module.js order-processor python WI-DEMO
```

Codex will run the 4-agent pipeline:

1. **Analyzer** (o4, read-only) — reads the Lambda, maps AWS dependencies, scores complexity
2. **Coder** (codex-mini) — proposes sprint contract, writes tests first, then migrates the code
3. **Tester** (o4-mini) — finalizes sprint contract, runs 3-layer evaluation
4. **Reviewer** (o4, read-only) — 8-point quality gate, decides APPROVE/BLOCK

Output appears in:
```
migration-analysis/order-processor/
├── analysis.md              Dependency map + complexity score
├── sprint-contract.json     Negotiated done-criteria
├── test-results.md          Unit + integration + contract results
├── review.md                8-point checklist + confidence score
└── eval-failures.json       Structured failure reports (if any)

src/azure-functions/order-processor/
├── function_app.py          Migrated Azure Function (v2 decorator model)
├── requirements.txt         azure-cosmos, azure-storage-blob, etc.
├── host.json                Azure Functions config
└── tests/                   Unit tests

infrastructure/order-processor/
└── main.bicep               Azure resources (Function App + Cosmos + Blob + Queue)
```

## Option B: Run via REST API

The orchestrator wraps the scaffolding as a REST service.

```bash
# 1. Install dependencies
pip install -r orchestrator/requirements.txt

# 2. Copy sample Lambda into place
mkdir -p src/lambda/order-processor
cp example/lambda/* src/lambda/order-processor/

# 3. Start the API
uvicorn orchestrator.api:app --port 8000

# 4. Trigger migration (synchronous — blocks until complete)
curl -X POST http://localhost:8000/migrate/sync \
  -H "Content-Type: application/json" \
  -d '{
    "module": "order-processor",
    "language": "python",
    "work_item_id": "WI-DEMO",
    "title": "Migrate order-processor to Azure Functions"
  }'

# 5. Check status
curl http://localhost:8000/status/order-processor

# 6. Or trigger async (returns immediately, runs in background)
curl -X POST http://localhost:8000/migrate \
  -H "Content-Type: application/json" \
  -d '{"module": "order-processor", "language": "python"}'
```

## Option C: Run via Docker

```bash
# Build the container image
docker build -t codex-harness .

# Copy sample Lambda into place first
mkdir -p src/lambda/order-processor
cp example/lambda/* src/lambda/order-processor/

# Run the orchestrator
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -v $(pwd)/src/lambda:/app/codex-harness/src/lambda:ro \
  codex-harness

# Then call the API as in Option B
```

## What the Migration Produces

The coder agent transforms:

| AWS (Lambda) | Azure (Functions) |
|-------------|-------------------|
| `def lambda_handler(event, context)` | `@app.route()` decorator |
| `boto3.resource('dynamodb')` | `CosmosClient` (azure-cosmos) |
| `boto3.client('s3')` | `BlobServiceClient` (azure-storage-blob) |
| `boto3.client('sqs')` | `QueueClient` (azure-storage-queue) |
| API Gateway proxy response | `func.HttpResponse` |
| IAM Roles | Managed Identity (DefaultAzureCredential) |

## Scaffolding Explained

The `.codex/` directory is the scaffolding package:

| Component | Purpose |
|-----------|---------|
| `agents/*.toml` | 4 agent definitions with model, sandbox, and instructions |
| `config.toml` | Codex project config (models, hooks, protected paths) |
| `program.md` | Human steering document (edit to change constraints mid-run) |
| `scripts/` | CLI runners (`migrate-module.js`, `migrate-batch.js`) |
| `scripts/hooks/` | Enforcement hooks (lint, secrets, pre-commit gates) |
| `templates/` | Sprint contract + failure report JSON schemas |
| `state/` | Persistent state (learned rules, progress, coverage baseline) |

The `AGENTS.md` at the project root provides migration guidance that Codex loads
automatically via its hierarchical instruction system.
