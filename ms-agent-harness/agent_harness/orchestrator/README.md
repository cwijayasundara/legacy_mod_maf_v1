# Orchestrator API — Triggering the MS Agent Framework Migration Service

Same REST interface as the codex-harness orchestrator, but agents run in-process
using Microsoft Agent Framework (`Agent` + `@tool` + `FoundryChatClient`).

## Starting the Service

### Local

```bash
# Azure AI Foundry (production)
export FOUNDRY_PROJECT_ENDPOINT=https://your-project.services.ai.azure.com
export FOUNDRY_MODEL=gpt-4o

# Or OpenAI directly (local dev)
export OPENAI_API_KEY=sk-...

# Install and run
pip install -r orchestrator/requirements.txt
mkdir -p src/lambda/order-processor && cp sample/lambda/* src/lambda/order-processor/
uvicorn orchestrator.api:app --host 0.0.0.0 --port 8000
```

### Docker

```bash
docker build -t ms-agent-harness .
docker run -p 8000:8000 \
  -e FOUNDRY_PROJECT_ENDPOINT=$FOUNDRY_PROJECT_ENDPOINT \
  -e FOUNDRY_MODEL=gpt-4o \
  ms-agent-harness
```

## API Endpoints

### Health Check

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "healthy",
  "framework": "microsoft-agent-framework",
  "foundry_configured": true,
  "ado_configured": false
}
```

### Trigger Migration (async — production)

```bash
curl -X POST http://localhost:8000/migrate \
  -H "Content-Type: application/json" \
  -d '{
    "module": "order-processor",
    "language": "python",
    "work_item_id": "WI-1001",
    "title": "Migrate order-processor to Azure Functions",
    "acceptance_criteria": "All unit tests pass, Bicep template generated"
  }'
```

Returns immediately:
```json
{
  "status": "accepted",
  "module": "order-processor",
  "work_item_id": "WI-1001",
  "message": "Migration queued for order-processor (python)"
}
```

### Trigger Migration (sync — demos)

```bash
curl -X POST http://localhost:8000/migrate/sync \
  -H "Content-Type: application/json" \
  -d '{"module": "order-processor", "language": "python"}'
```

Blocks until pipeline completes:
```json
{
  "status": "completed",
  "module": "order-processor",
  "work_item_id": "LOCAL",
  "message": "Migration approved (score: 82/100)",
  "review_score": 82
}
```

### Check Status

```bash
# Single module
curl http://localhost:8000/status/order-processor

# All modules
curl http://localhost:8000/status
```

## What Happens When You Trigger

```
POST /migrate
    │
    ├── 1. Pull state (learned rules, progress, coverage baseline)
    │
    ├── 2. Analyzer agent (gpt-4o)
    │      • Reads Lambda source via @tool functions
    │      • Scores complexity (12 weighted patterns)
    │      • Chunks large files at AST boundaries
    │      • Writes analysis.md
    │      • Caches results in SQLite (skip on retry)
    │
    ├── 3. Sprint Contract Negotiation
    │      • Coder proposes contract (what PASS means)
    │      • Tester finalizes (adds/removes checks)
    │      • Contract is immutable after finalization
    │
    ├── 4. Self-Healing Loop (up to 3 attempts)
    │      ┌─ Coder agent (gpt-4o-mini)
    │      │  • TDD-first: tests then code
    │      │  • AWS SDK → Azure SDK replacement
    │      │  • Generates Bicep template
    │      │
    │      ├─ Tester agent (gpt-4o-mini)
    │      │  • 3-layer evaluation (unit, integration, contract)
    │      │  • Structured failure report (10 error categories)
    │      │  • Coverage ratchet enforcement
    │      │
    │      └─ On FAIL: failure report feeds back to coder
    │
    ├── 5. Reviewer agent (gpt-4o)
    │      • 8-point quality gate
    │      • APPROVE / CHANGES_REQUESTED / BLOCKED
    │
    ├── 6. Push state (update learned rules, progress)
    │
    └── 7. Create PR in ADO (if configured)
```

## Request Fields

| Field | Required | Description |
|-------|----------|-------------|
| `module` | yes | Directory name under `src/lambda/` |
| `language` | yes | `python`, `node`, `java`, or `csharp` |
| `work_item_id` | no | ADO work item ID (default: `LOCAL`) |
| `title` | no | Work item title |
| `description` | no | Work item description |
| `acceptance_criteria` | no | Criteria for reviewer validation |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FOUNDRY_PROJECT_ENDPOINT` | yes* | Azure AI Foundry project endpoint |
| `FOUNDRY_MODEL` | no | Default model (default: `gpt-4o`) |
| `OPENAI_API_KEY` | yes* | Fallback: direct OpenAI key |
| `PROJECT_ROOT` | no | Path to project root |
| `MAX_CONCURRENT_MIGRATIONS` | no | Max parallel migrations (default: 3) |
| `AZURE_STORAGE_CONNECTION_STRING` | no | For state persistence in Blob Storage |
| `ADO_ORG_URL` | no | Azure DevOps org URL (for PR creation) |
| `ADO_PROJECT` | no | ADO project name |
| `ADO_REPO` | no | ADO repository name |
| `ADO_PAT` | no | ADO personal access token |

*Either `FOUNDRY_PROJECT_ENDPOINT` or `OPENAI_API_KEY` must be set.

## Interactive Docs

Swagger UI: `http://localhost:8000/docs`
