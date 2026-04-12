# Orchestrator API — Triggering the Codex Migration Service

The orchestrator is a FastAPI application that exposes the `.codex/` scaffolding as a
REST service. It wraps the Codex CLI, manages persistent state, and optionally creates
PRs in Azure DevOps.

## Starting the Service

### Local (development)

```bash
# Install dependencies
pip install -r requirements.txt

# Set API key (OpenAI or Azure OpenAI)
export OPENAI_API_KEY=sk-...

# For Azure OpenAI endpoint:
# export CODEX_API_BASE=https://YOUR_PROJECT.openai.azure.com/openai/v1

# Ensure your Lambda source is in place
mkdir -p src/lambda/order-processor
cp example/lambda/* src/lambda/order-processor/

# Start the service
uvicorn orchestrator.api:app --host 0.0.0.0 --port 8000
```

### Docker

```bash
docker build -t codex-harness .
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -v $(pwd)/src/lambda:/app/codex-harness/src/lambda:ro \
  codex-harness
```

## API Endpoints

### Health Check

```
GET /health
```

Verifies the service is running and checks availability of Codex CLI, state storage,
and ADO connection.

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "healthy",
  "codex_available": true,
  "state_connected": false,
  "ado_connected": false
}
```

---

### Trigger Migration (async)

```
POST /migrate
```

Starts a migration in the background. Returns `200` immediately with status `accepted`.
Use this for production workflows where you don't want to block the caller.

**Request:**

```bash
curl -X POST http://localhost:8000/migrate \
  -H "Content-Type: application/json" \
  -d '{
    "module": "order-processor",
    "language": "python",
    "work_item_id": "WI-1001",
    "title": "Migrate order-processor to Azure Functions",
    "description": "Convert DynamoDB + S3 + SQS dependencies to Azure equivalents",
    "acceptance_criteria": "All unit tests pass, Bicep template generated"
  }'
```

**Response:**

```json
{
  "status": "accepted",
  "module": "order-processor",
  "work_item_id": "WI-1001",
  "message": "Migration queued for order-processor (python)"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `module` | yes | Directory name under `src/lambda/` |
| `language` | yes | `python`, `java`, `node`, or `csharp` |
| `work_item_id` | no | ADO work item ID (default: `LOCAL`) |
| `title` | no | Work item title (passed to agent prompt) |
| `description` | no | Work item description |
| `acceptance_criteria` | no | Acceptance criteria for the reviewer |

---

### Trigger Migration (sync)

```
POST /migrate/sync
```

Same as `/migrate` but blocks until the migration pipeline completes. Use this for
demos and testing.

```bash
curl -X POST http://localhost:8000/migrate/sync \
  -H "Content-Type: application/json" \
  -d '{
    "module": "order-processor",
    "language": "python"
  }'
```

**Response (on success):**

```json
{
  "status": "completed",
  "module": "order-processor",
  "work_item_id": "LOCAL",
  "message": "Migration complete. PR created.",
  "pr_url": "https://dev.azure.com/.../pullrequest/42",
  "review_score": null
}
```

**Response (on block):**

```json
{
  "status": "blocked",
  "module": "order-processor",
  "work_item_id": "LOCAL",
  "message": "Migration blocked after 3 self-healing attempts. See blocked.md."
}
```

---

### Check Migration Status

```
GET /status/{module}
```

Returns the latest migration status for a specific module.

```bash
curl http://localhost:8000/status/order-processor
```

```json
{
  "module": "order-processor",
  "status": "approve",
  "gates_passed": [1, 2, 3, 4, 5, 6],
  "gates_failed": [],
  "coverage": 87.5,
  "reviewer_score": 82,
  "blocked": false,
  "block_reason": ""
}
```

---

### List All Migrations

```
GET /status
```

Returns status of all modules that have been processed.

```bash
curl http://localhost:8000/status
```

---

### Queue Webhook (production)

```
POST /webhook/queue
```

Receives messages from Azure Queue Storage (posted by the ADO trigger function).
This is the production entry point when deployed as a Container App.

```bash
curl -X POST http://localhost:8000/webhook/queue \
  -H "Content-Type: application/json" \
  -d '{
    "module": "order-processor",
    "language": "python",
    "work_item_id": "WI-1001",
    "title": "Migrate order-processor"
  }'
```

---

## What Happens When You Trigger a Migration

```
POST /migrate
    │
    ├── 1. Pull state from Azure Blob Storage (learned rules, progress, coverage)
    │
    ├── 2. Create output directories (migration-analysis/, src/azure-functions/, etc.)
    │
    ├── 3. Compose prompt with module context + work item details
    │
    ├── 4. Run Codex CLI (--approval-mode full-auto)
    │      Codex reads .codex/ scaffolding and runs 4 agents:
    │
    │      ┌─ Analyzer (o4, read-only)
    │      │  Reads Lambda source → analysis.md
    │      │
    │      ├─ Coder (codex-mini, write)
    │      │  Proposes sprint contract → writes tests → migrates code → Bicep template
    │      │
    │      ├─ Tester (o4-mini, write)
    │      │  Finalizes contract → 3-layer evaluation → structured failure reports
    │      │
    │      └─ Reviewer (o4, read-only)
    │         8-point checklist → APPROVE / CHANGES_REQUESTED / BLOCKED
    │
    ├── 5. Push updated state to Blob Storage
    │
    ├── 6. If APPROVED: create PR in Azure DevOps (if configured)
    │
    └── 7. Return result
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | yes | — | OpenAI or Azure OpenAI API key |
| `CODEX_API_BASE` | no | — | Azure OpenAI endpoint URL |
| `CODEX_MODEL` | no | `o4-mini` | Default Codex model |
| `PROJECT_ROOT` | no | `/app/codex-harness` | Path to project root |
| `MAX_CONCURRENT_MIGRATIONS` | no | `3` | Max parallel migrations |
| `AZURE_STORAGE_CONNECTION_STRING` | no | — | For state persistence in Blob Storage |
| `STATE_CONTAINER` | no | `migration-state` | Blob container name |
| `ADO_ORG_URL` | no | — | Azure DevOps org URL |
| `ADO_PROJECT` | no | — | ADO project name |
| `ADO_REPO` | no | — | ADO repository name |
| `ADO_PAT` | no | — | ADO personal access token |

When `AZURE_STORAGE_CONNECTION_STRING` is not set, state is stored locally only.
When `ADO_*` variables are not set, PR creation is skipped.

## Interactive API Docs

When the service is running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
