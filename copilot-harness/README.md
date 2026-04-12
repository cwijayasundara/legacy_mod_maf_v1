# Copilot Harness — AWS Lambda to Azure Functions Migration

Migration framework built on [GitHub Copilot CLI](https://docs.github.com/en/copilot/using-github-copilot/using-github-copilot-in-the-command-line) with [BYOK support](https://github.blog/changelog/2026-04-07-copilot-cli-now-supports-byok-and-local-models/) for Azure OpenAI. Uses Copilot's built-in sub-agents (Explore, Task, Review, Plan) for automatic delegation, plus the [Copilot SDK](https://github.com/github/copilot-sdk) for fine-grained security review.

## Structure

```
copilot-harness/
│
├── .copilot/                            ← COPILOT PACKAGE (loaded by Copilot CLI)
│   ├── config.yml                       BYOK settings, permissions, hooks
│   ├── AGENTS.md                        Migration guidance
│   ├── quality-principles.md            6 code quality rules
│   ├── architecture.md                  Layered dependency rules
│   └── hooks/                           Node.js enforcement hooks (7 files)
│
├── harness/                             ← HARNESS PACKAGE (custom code)
│   ├── copilot_runner.py                Wraps `copilot --autopilot --yolo` with BYOK
│   ├── sdk_agents.py                    Copilot SDK agents (security review)
│   ├── pipeline.py                      7-gate orchestrator (CLI + SDK)
│   └── orchestrator/                    REST API (same interface as other harnesses)
│       ├── api.py                       FastAPI: /migrate, /status, /health
│       ├── ado_client.py                ADO REST (PRs, work items)
│       └── state_manager.py             State persistence
│
├── example/                             ← SAMPLE LAMBDA
│   ├── lambda/handler.py                Order processor (DynamoDB + S3 + SQS)
│   └── README.md
│
├── config/                              ← CONFIGURATION
│   ├── settings.yaml                    BYOK env vars, timeouts, quality thresholds
│   ├── program.md                       Human steering
│   ├── templates/                       Sprint contract + failure report schemas
│   └── state/                           Learned rules, progress, coverage baseline
│
├── migrated_code/                       ← OUTPUT (generated at runtime)
├── tests/                               ← TESTS
├── requirements.txt
└── Dockerfile
```

## Prerequisites

```bash
# Node.js 18+
node --version

# Python 3.11+
python3 --version

# Copilot CLI (install via npm)
npm install -g @githubnext/copilot-cli
```

## Setup

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Set credentials — choose ONE method:

#   Method A: BYOK with Azure OpenAI (recommended for production)
export COPILOT_PROVIDER_BASE_URL=https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT
export COPILOT_PROVIDER_TYPE=azure
export COPILOT_PROVIDER_API_KEY=YOUR-KEY
export COPILOT_MODEL=YOUR-DEPLOYMENT-NAME
export COPILOT_OFFLINE=true

#   Method B: BYOK with OpenAI directly
export COPILOT_PROVIDER_TYPE=openai
export COPILOT_PROVIDER_API_KEY=sk-...
export COPILOT_OFFLINE=true

#   Method C: GitHub authentication (uses GitHub's models)
copilot login

#   Method D: .env file
echo "OPENAI_API_KEY=sk-..." > ../.env

# 3. Copy example Lambda into place
mkdir -p src/lambda/order-processor
cp example/lambda/* src/lambda/order-processor/
```

## Running the Migration

### Option A: Via Copilot CLI (direct)

```bash
copilot --autopilot --yolo -p "Migrate src/lambda/order-processor/ to Azure Functions following .copilot/AGENTS.md"
```

### Option B: Via REST API

```bash
# Start the orchestrator
uvicorn harness.orchestrator.api:app --host 0.0.0.0 --port 8000

# Trigger migration (async)
curl -X POST http://localhost:8000/migrate \
  -H "Content-Type: application/json" \
  -d '{
    "module": "order-processor",
    "language": "python",
    "work_item_id": "WI-1001"
  }'

# Trigger migration (sync — blocks until complete)
curl -X POST http://localhost:8000/migrate/sync \
  -H "Content-Type: application/json" \
  -d '{"module": "order-processor", "language": "python"}'

# Health check
curl http://localhost:8000/health
```

### Option C: Via Docker

```bash
docker build -t copilot-harness .
docker run -p 8000:8000 \
  -e COPILOT_PROVIDER_TYPE=openai \
  -e COPILOT_PROVIDER_API_KEY=$OPENAI_API_KEY \
  -e COPILOT_OFFLINE=true \
  copilot-harness
```

## What Happens During Migration (7 Gates)

```
Gates 1-6: Copilot CLI (built-in sub-agents auto-delegate)
   → Copilot reads .copilot/AGENTS.md for migration guidance
   → Built-in Explore agent analyzes the Lambda
   → Built-in Task agent handles TDD migration
   → Built-in Review agent evaluates quality
   → Sprint contracts, learned rules, coverage ratcheting all enforced

Gate 7: Security Review (via Copilot SDK)
   → Automated OWASP regex scan
   → SDK-based LLM deep analysis
   → Output: migration-analysis/{module}/security-review.md
```

## Key Advantage: Built-in Sub-Agents

Unlike Codex CLI (which needs manual TOML agent definitions), Copilot CLI
automatically delegates to specialized built-in agents:

| Built-in Agent | What it does | Codex equivalent |
|---------------|-------------|-----------------|
| **Explore** | Code search, dependency analysis | analyzer.toml |
| **Task** | Implementation, code generation | coder.toml |
| **Review** | Code review, quality checks | reviewer.toml |
| **Plan** | Architecture planning | (manual prompt) |

You write the migration guidance in `.copilot/AGENTS.md` and Copilot
decides which sub-agent handles each part of the task.

## How It Differs From Other Harnesses

| Aspect | codex-harness | copilot-harness | ms-agent-harness |
|--------|--------------|----------------|-----------------|
| CLI command | `codex exec --full-auto` | `copilot --autopilot --yolo` | (in-process Python) |
| Agent definitions | Manual TOML (5 files) | **Auto-delegation** (built-in) | Python classes |
| BYOK Azure | Native | `COPILOT_PROVIDER_*` env vars | FoundryChatClient |
| SDK | None | **Copilot SDK** (Python) | Agent Framework |
| No auth needed | API key only | `COPILOT_OFFLINE=true` | API key only |
| Sub-agent control | Explicit per-agent | Copilot decides | Custom pipeline |
| Hooks | Node.js (7 files) | Same Node.js hooks | Python quality/ pkg |

## Running Tests

```bash
pip install pytest pytest-cov pytest-asyncio httpx
pytest tests/ -v
```
