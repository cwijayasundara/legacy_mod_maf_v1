# Orchestrator API — Triggering the Copilot CLI Migration Service

Same REST interface as codex-harness and ms-agent-harness.
Wraps Copilot CLI in `--autopilot --yolo` mode with BYOK Azure OpenAI support.

## Starting the Service

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...   # or set COPILOT_PROVIDER_* for BYOK
mkdir -p src/lambda/order-processor && cp example/lambda/* src/lambda/order-processor/
uvicorn harness.orchestrator.api:app --host 0.0.0.0 --port 8000
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (Copilot available, BYOK configured, ADO configured) |
| POST | `/migrate` | Start migration async (returns immediately) |
| POST | `/migrate/sync` | Start migration sync (blocks until complete) |
| GET | `/status/{module}` | Check module status |
| GET | `/status` | List all migrations |

## Request Body

```json
{
  "module": "order-processor",
  "language": "python",
  "work_item_id": "WI-1001",
  "title": "Migrate order-processor",
  "description": "...",
  "acceptance_criteria": "..."
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `COPILOT_PROVIDER_BASE_URL` | no | Azure OpenAI endpoint (BYOK) |
| `COPILOT_PROVIDER_TYPE` | no | `azure`, `openai`, `anthropic`, `ollama` |
| `COPILOT_PROVIDER_API_KEY` | no | API key for BYOK provider |
| `COPILOT_MODEL` | no | Model/deployment name |
| `COPILOT_OFFLINE` | no | `true` to skip GitHub auth |
| `OPENAI_API_KEY` | yes* | Fallback API key |
| `ADO_ORG_URL` | no | Azure DevOps org (for PR creation) |
| `ADO_PROJECT` | no | ADO project |
| `ADO_REPO` | no | ADO repository |
| `ADO_PAT` | no | ADO personal access token |

*Either BYOK env vars or OPENAI_API_KEY must be set.

## Swagger UI

`http://localhost:8000/docs`
