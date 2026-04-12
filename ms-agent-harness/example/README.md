# Sample: Migrating a Python Lambda with MS Agent Framework

Same example as codex-harness — a Python Lambda with DynamoDB + S3 + SQS — but
migrated using Microsoft Agent Framework agents running in-process.

## The Source Lambda

```
sample/lambda/
├── handler.py          Order processor (POST/GET /orders)
└── requirements.txt    boto3
```

## Run the Migration

```bash
# Set credentials (Azure AI Foundry or OpenAI)
export FOUNDRY_PROJECT_ENDPOINT=https://your-project.services.ai.azure.com
# Or: export OPENAI_API_KEY=sk-...

# Install
pip install -r orchestrator/requirements.txt

# Place Lambda source
mkdir -p src/lambda/order-processor
cp sample/lambda/* src/lambda/order-processor/

# Start API and trigger migration
uvicorn orchestrator.api:app --port 8000 &
curl -X POST http://localhost:8000/migrate/sync \
  -H "Content-Type: application/json" \
  -d '{"module": "order-processor", "language": "python"}'
```

## What's Different From codex-harness

The agents run **inside the Python process** — no Codex CLI binary needed.
Each agent is an `Agent()` instance from `agent-framework` with `@tool` functions:

```python
from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient

@tool(approval_mode="never_require")
def read_file(path: str) -> str:
    return Path(path).read_text()

analyzer = Agent(
    client=FoundryChatClient(project_endpoint=..., model="gpt-4o", credential=...),
    name="migration-analyzer",
    instructions=open("agents/prompts/analyzer.md").read(),
    tools=[read_file, search_files, parse_imports, find_aws_dependencies],
)
result = await analyzer.run("Analyze src/lambda/order-processor/")
```

Context engineering features not available in codex-harness:
- **Semantic chunking**: large files split at function boundaries, not arbitrary lines
- **Progressive compression**: older chunks compressed to 30%, recent 3 at full detail
- **Token budgets**: complexity-aware estimation (chars ÷ 3.0 × multiplier)
- **SQLite caching**: analysis cached, skip on retry; chunk status for resume
- **Speed profiles**: Turbo/Fast/Balanced/Thorough control quality vs cost
