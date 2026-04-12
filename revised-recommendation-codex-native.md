# Revised Recommendation: Codex-Native Architecture

## Addendum to AWS-to-Azure Migration Coding Agents Research

**Date:** April 11, 2026  
**Revision trigger:** Codex natively supports sub-agents with TOML-based custom agent definitions, eliminating the need for a separate orchestration layer.

---

## 1. What Changes: The Separate Orchestration Layer is Unnecessary

The original recommendation proposed Codex as the coding engine plus a **separate orchestration layer** (Copilot SDK or Open SWE) for sub-agent coordination. With Codex's native sub-agent support, this extra layer is redundant. Codex already provides:

**Native sub-agent orchestration:**
- A manager agent decomposes tasks into subtasks and spawns specialized worker agents in parallel
- Each sub-agent runs in its own isolated cloud sandbox with full filesystem, dependencies, and tool access
- Codex handles spawning, routing follow-up instructions, waiting for results, and closing agent threads
- Consolidated responses returned when all sub-agents complete

**Custom agent definitions as TOML files:**
- Defined in `~/.codex/agents/` (global) or `.codex/agents/` (project-local)
- Full control over model, reasoning effort, sandbox permissions, and system prompt per agent
- Agents inherit parent session settings unless explicitly overridden

**Built-in agent archetypes:**
- `explorer` — reads and understands code without modification
- `worker` — executes parallel tasks at scale
- `default` — general-purpose agent

**Project-level guidance via AGENTS.md:**
- Hierarchical instructions that travel with the repository
- AGENTS.override.md > AGENTS.md > TEAM_GUIDE.md precedence
- Per-directory scoping (e.g., different rules for `/src/java/` vs `/src/python/`)

This means your architecture simplifies from:

```
BEFORE:  ADO --> Trigger --> Orchestrator (Copilot SDK / Open SWE) --> Codex sub-tasks
AFTER:   ADO --> Trigger --> Codex (with native sub-agents) --> Done
```

The only custom component you still need is a **thin trigger layer** (Azure Function receiving ADO webhooks) that kicks off Codex tasks. Codex handles everything else internally.

---

## 2. Porting Your Claude Harness Engine to Codex

Your [Claude Harness Engine](https://github.com/cwijayasundara/claude_harness_eng_v1) maps almost 1:1 onto Codex's architecture. Here's the conversion:

### 2.1 Structural Mapping

```
CLAUDE HARNESS ENGINE          -->    CODEX EQUIVALENT
─────────────────────────────        ─────────────────────────
.claude/                       -->    .codex/
  skills/                      -->    agents/ (TOML files)
  agents/                      -->    agents/ (TOML files)
  commands/                    -->    AGENTS.md sections + CLI triggers
  hooks/                       -->    config.toml [hooks] or pre/post scripts
  settings.json                -->    config.toml
CLAUDE.md                      -->    AGENTS.md (root-level project guidance)
design.md                      -->    AGENTS.md (architecture section)
```

### 2.2 Agent-by-Agent Conversion

Your harness uses a generator-evaluator pattern with multiple agent roles. Each becomes a Codex custom sub-agent:

#### Analyzer Agent (Explorer)

```toml
# .codex/agents/analyzer.toml
name = "migration-analyzer"
description = "Analyze Lambda modules for dependencies, business logic, and migration complexity"
model = "gpt-5.4"
model_reasoning_effort = "high"
sandbox_mode = "read-only"

[instructions]
text = """
You are a senior platform architect analyzing AWS Lambda modules for migration to Azure Functions.

## Your Responsibilities
1. Parse the module using Tree-sitter AST to extract function signatures, imports, and call graphs
2. Identify AWS SDK dependencies (boto3, aws-sdk, AWSSDK.*) and map to Azure equivalents
3. Extract business logic boundaries — separate infrastructure glue from domain logic
4. Map inter-service dependencies (HTTP calls, queue producers/consumers, shared libraries)
5. Score migration complexity (Low/Medium/High) based on:
   - Number of AWS-specific dependencies
   - Inter-service coupling
   - Language-specific migration complexity
   - Presence of Step Functions or complex event patterns

## Output Format
Write findings to `migration-analysis/{module-name}/analysis.md` with:
- Dependency inventory (AWS resources, inter-service calls, shared libs)
- Business logic summary
- Complexity score and rationale
- Recommended migration order
- Azure resource mapping table
"""
```

#### Coder Agent (Generator)

```toml
# .codex/agents/coder.toml
name = "migration-coder"
description = "Migrate Lambda handlers to Azure Functions, replacing AWS SDK with Azure SDK"
model = "codex-mini"
model_reasoning_effort = "high"
sandbox_mode = "workspace-write"

[instructions]
text = """
You are a senior full-stack engineer migrating AWS Lambda functions to Azure Functions.

## TDD-First Rule (MANDATORY)
You MUST write tests BEFORE writing migration code. Sequence:
1. Read the analyzer's output in migration-analysis/{module-name}/
2. Write unit tests that capture the existing business logic behavior
3. Run tests against the original code to establish baseline (green)
4. Write the Azure Function equivalent
5. Run tests against the new code — must pass identically
6. Only then commit to the migration branch

## Migration Patterns by Language

### Java
- AWS: `RequestHandler<Input, Output>` --> Azure: `@FunctionName` annotation
- Replace `com.amazonaws.*` with `com.azure.*`
- Maven: swap AWS SDK BOM for Azure SDK BOM
- Handler: `handleRequest(input, Context)` --> `run(@HttpTrigger ... req, ExecutionContext ctx)`

### Python
- AWS: `def lambda_handler(event, context)` --> Azure: `@app.function_name()` decorator
- Replace `boto3` with `azure-storage-blob`, `azure-cosmos`, etc.
- requirements.txt: swap AWS packages for Azure packages

### Node.js
- AWS: `exports.handler = async (event)` --> Azure: `module.exports = async function(context, req)`
- Replace `@aws-sdk/*` with `@azure/*`
- package.json: swap dependencies

### C#
- AWS: `ILambdaContext` --> Azure: `FunctionContext`
- Replace `AWSSDK.*` NuGet packages with `Azure.*`
- This is the closest mapping of all languages

## Ratcheting Rule
Code quality only moves forward. If tests regress, revert and retry (up to 3 attempts).
If 3 attempts fail, write a detailed failure report to migration-analysis/{module-name}/blocked.md
and stop — do NOT commit broken code.

## AWS to Azure Resource Mapping
- S3 --> Azure Blob Storage (azure-storage-blob)
- SQS --> Azure Queue Storage / Service Bus
- SNS --> Azure Event Grid / Service Bus Topics
- DynamoDB --> Azure Cosmos DB (Table API)
- RDS PostgreSQL --> Azure Database for PostgreSQL (connection string only)
- CloudWatch --> Azure Monitor / Application Insights
- Secrets Manager --> Azure Key Vault
- IAM Roles --> Managed Identity
"""
```

#### Tester Agent (Evaluator)

```toml
# .codex/agents/tester.toml
name = "migration-tester"
description = "Validate migrated Azure Functions against original Lambda behavior"
model = "gpt-5.3-codex-spark"
model_reasoning_effort = "medium"
sandbox_mode = "workspace-write"

[instructions]
text = """
You are a QA engineer validating AWS-to-Azure function migrations.

## Three-Layer Evaluation (from Harness Engine)

### Layer 1: Unit Tests
- Run all unit tests for the migrated module
- Compare outputs against baseline recorded from Lambda version
- 100% meaningful coverage target, 80% minimum floor

### Layer 2: Integration Tests
- Test Azure SDK interactions (Blob Storage, Cosmos DB, Service Bus)
- Use Azure emulators or test containers where available
- Verify connection strings, managed identity configs

### Layer 3: Contract Validation
- Verify API contracts (request/response schemas) are preserved
- Check event trigger schemas match original
- Validate error handling and retry behavior

## Self-Healing Protocol
If tests fail:
1. Attempt 1: Analyze failure, fix the obvious issue
2. Attempt 2: Re-read original Lambda code, identify missed behavior
3. Attempt 3: Simplify approach, focus on core business logic
After 3 failures: write detailed report to migration-analysis/{module-name}/test-failures.md
"""
```

#### Reviewer Agent (Quality Gate)

```toml
# .codex/agents/reviewer.toml
name = "migration-reviewer"
description = "Code review migrated Azure Functions against migration checklist"
model = "gpt-5.4"
model_reasoning_effort = "high"
sandbox_mode = "read-only"

[instructions]
text = """
You are a senior architect reviewing migrated Azure Functions code.

## Review Checklist
1. Business logic preservation — does the Azure version do exactly what the Lambda did?
2. No AWS artifacts remaining — no boto3, aws-sdk, AWSSDK imports
3. Azure best practices — Managed Identity (not hardcoded keys), proper DI, function.json correct
4. Error handling — retry policies, dead letter queues, poison message handling
5. Configuration — all env vars mapped to Azure App Settings / Key Vault references
6. Security — no secrets in code, no hardcoded endpoints, proper CORS/auth
7. Performance — cold start optimization, async patterns, connection pooling
8. Infrastructure — Bicep/ARM templates present and valid

## Sprint Contract Validation
Compare deliverables against the acceptance criteria from the ADO work item.
Write review summary to migration-analysis/{module-name}/review.md with:
- PASS/FAIL per checklist item
- Confidence score (0-100)
- Issues found (blocking vs non-blocking)
- Recommendation: APPROVE / CHANGES_REQUESTED / BLOCKED
"""
```

### 2.3 Root AGENTS.md (Replaces CLAUDE.md)

```markdown
# AGENTS.md — AWS Lambda to Azure Functions Migration

## Project Context
This is a multi-language (Java, Python, Node.js, C#) AWS Lambda platform being migrated
to Azure Functions. Each module has been analyzed and assigned a migration work item in ADO.

## Migration Principles
1. **TDD-First**: Tests before code. Always.
2. **Ratcheting**: Quality only moves forward. No regressions committed.
3. **Generator-Evaluator Separation**: The coder never reviews their own work.
4. **Leaves First**: Migrate modules with no inbound dependencies first.
5. **Business Logic Preservation**: The migrated function MUST behave identically.

## Workflow per Module
1. Analyzer reads the module, produces dependency map and complexity score
2. Coder writes tests, then migrates (TDD-first with ratcheting)
3. Tester validates across 3 layers (unit, integration, contract)
4. Reviewer gates quality before PR creation

## Directory Structure
- `/migration-analysis/{module}/` — analyzer output, test reports, review summaries
- `/src/azure-functions/{module}/` — migrated Azure Function code
- `/infrastructure/{module}/` — Bicep templates per module
- `/tests/{module}/` — unit and integration tests

## Conventions
- All commits reference the ADO work item ID: `[WI-{id}] description`
- PR descriptions include: what was migrated, what changed, confidence score
- Blocked modules get a `blocked.md` with root cause analysis
```

### 2.4 Per-Language AGENTS.md Overrides

```markdown
# src/java/AGENTS.md
## Java-Specific Migration Rules
- Use Azure Functions Java library v4+ (annotation-based, not function.json)
- Maven BOM: com.azure:azure-sdk-bom
- Replace AWS Lambda Powertools with Azure Monitor OpenTelemetry
- Use @FunctionName, @HttpTrigger, @QueueTrigger annotations
- Connection pooling via static HttpClient instances
```

```markdown
# src/python/AGENTS.md
## Python-Specific Migration Rules
- Use Azure Functions Python v2 programming model (decorator-based)
- Replace boto3.client('s3') with BlobServiceClient
- Replace boto3.client('sqs') with QueueClient
- Use azure-identity DefaultAzureCredential for all auth
- requirements.txt must pin all Azure SDK versions
```

---

## 3. Revised Architecture

```
+------------------------------------------------------------------+
|                    AZURE AI FOUNDRY                               |
|                                                                  |
|  +------------------------------------------------------------+  |
|  |          TRIGGER LAYER (only custom component)              |  |
|  |  Azure Function: receives ADO Service Hook webhook          |  |
|  |  Dispatches Codex task with work item context               |  |
|  +----+-------------------------------------------------+-----+  |
|       |                                                          |
|  +----v----------------------------------------------------+     |
|  |              CODEX (Azure OpenAI endpoint)               |    |
|  |              Root AGENTS.md loaded                       |    |
|  |                                                          |    |
|  |  Codex manager reads work item, decomposes task,         |    |
|  |  spawns sub-agents in parallel:                          |    |
|  |                                                          |    |
|  |  +------------+ +------------+ +----------+ +----------+ |    |
|  |  | analyzer   | | coder      | | tester   | | reviewer | |    |
|  |  | .toml      | | .toml      | | .toml    | | .toml    | |    |
|  |  |            | |            | |          | |          | |    |
|  |  | read-only  | | workspace  | | workspace| | read-only| |    |
|  |  | gpt-5.4    | | codex-mini | | spark    | | gpt-5.4  | |    |
|  |  +------------+ +------------+ +----------+ +----------+ |    |
|  |                                                          |    |
|  |  Codex consolidates results, creates branch, raises PR   |    |
|  +----------------------------------------------------------+    |
|                                                                  |
|  +------------------------------------------------------------+  |
|  |          SHARED CONTEXT (via AGENTS.md hierarchy)           |  |
|  |  Root: migration principles, workflow, conventions          |  |
|  |  /src/java/: Java-specific migration rules                  |  |
|  |  /src/python/: Python-specific migration rules              |  |
|  |  /src/node/: Node.js-specific migration rules               |  |
|  |  /src/csharp/: C#-specific migration rules                  |  |
|  +------------------------------------------------------------+  |
+------------------------------------------------------------------+
```

### What You Build vs What Codex Provides

| Concern | Who Handles It |
|---|---|
| Sub-agent orchestration | **Codex** (native manager --> worker pattern) |
| Parallel execution | **Codex** (each sub-agent in isolated sandbox) |
| Context per agent | **Codex** (TOML instructions + AGENTS.md hierarchy) |
| Model routing per task | **Codex** (model field per TOML agent) |
| Sandbox isolation | **Codex** (read-only vs workspace-write per agent) |
| Context compaction | **Codex** (server-side compaction via `compact_threshold`) |
| File search (ripgrep, glob) | **Codex** (built-in tools per sandbox) |
| ADO webhook reception | **You** (thin Azure Function, ~50 lines) |
| ADO PR creation | **You** (ADO REST API call after Codex completes) |
| Migration domain knowledge | **You** (AGENTS.md + per-language overrides) |
| Quality guardrails | **You** (ported from Harness Engine into TOML instructions) |
| Agent definitions | **You** (4 TOML files: analyzer, coder, tester, reviewer) |

---

## 4. What You Actually Need to Build

The total custom code shrinks dramatically:

### 4.1 Deliverables

```
Custom Code:
  1. ADO Webhook Trigger          ~100 lines (Azure Function)
  2. ADO PR Creation Helper       ~50 lines  (post-Codex script)

Configuration (no code):
  3. .codex/agents/analyzer.toml  ~40 lines
  4. .codex/agents/coder.toml     ~80 lines
  5. .codex/agents/tester.toml    ~50 lines
  6. .codex/agents/reviewer.toml  ~50 lines
  7. AGENTS.md (root)             ~60 lines
  8. AGENTS.md (per-language x4)  ~20 lines each

Total custom code: ~150 lines
Total configuration: ~360 lines of TOML/Markdown
```

Compare this to the original recommendation of building an orchestration layer (estimated 1-2 months). This approach is **days of work, not months**.

### 4.2 Trigger Function (Complete Implementation)

```python
"""
The ONLY custom code needed: ADO webhook --> Codex dispatch --> ADO PR creation
"""
import azure.functions as func
import json
import subprocess
import httpx
from azure.identity import DefaultAzureCredential

app = func.FunctionApp()

@app.function_name("migration-trigger")
@app.route(route="webhook/ado", methods=["POST"])
async def handle_workitem(req: func.HttpRequest) -> func.HttpResponse:
    payload = req.get_json()
    work_item = payload["resource"]
    
    # Only act on "Ready for Agent" state transitions
    if work_item["fields"]["System.State"] != "Ready for Agent":
        return func.HttpResponse("Skipped", status_code=200)
    
    wi_id = work_item["id"]
    title = work_item["fields"]["System.Title"]
    description = work_item["fields"]["System.Description"]
    module = work_item["fields"].get("Custom.TargetModule", "")
    language = work_item["fields"].get("Custom.SourceLanguage", "")
    criteria = work_item["fields"].get(
        "Microsoft.VSTS.Common.AcceptanceCriteria", ""
    )
    
    # Compose the Codex task prompt
    codex_prompt = f"""
    Migrate AWS Lambda module '{module}' ({language}) to Azure Functions.
    
    Work Item: WI-{wi_id} - {title}
    Description: {description}
    Acceptance Criteria: {criteria}
    
    Follow the workflow in AGENTS.md:
    1. Run analyzer agent on /src/lambda/{module}/
    2. Run coder agent to migrate (TDD-first, ratcheting)
    3. Run tester agent to validate (3-layer evaluation)
    4. Run reviewer agent to gate quality
    5. Create a branch: migrate/WI-{wi_id}-{module}
    6. Commit all changes with message: [WI-{wi_id}] Migrate {module} to Azure Functions
    """
    
    # Dispatch to Codex (running in Azure Container App)
    result = subprocess.run(
        ["codex", "--prompt", codex_prompt, "--approval-mode", "full-auto"],
        capture_output=True, text=True, timeout=3600,
        env={
            "CODEX_API_BASE": "https://YOUR_PROJECT.openai.azure.com/openai/v1",
            "CODEX_API_KEY": get_secret("azure-openai-key"),
        }
    )
    
    # After Codex completes, create PR in ADO
    if result.returncode == 0:
        await create_ado_pr(wi_id, module, language)
    
    return func.HttpResponse(f"Agent dispatched for WI-{wi_id}", status_code=202)


async def create_ado_pr(wi_id: str, module: str, language: str):
    """Create a PR in Azure DevOps linking back to the work item."""
    ado_org = "https://dev.azure.com/YOUR_ORG"
    ado_project = "YOUR_PROJECT"
    ado_repo = "YOUR_REPO"
    
    pr_body = {
        "sourceRefName": f"refs/heads/migrate/WI-{wi_id}-{module}",
        "targetRefName": "refs/heads/main",
        "title": f"[WI-{wi_id}] Migrate {module} ({language}) to Azure Functions",
        "description": f"Auto-generated by migration agent.\n\nSee migration-analysis/{module}/ for analysis, test results, and review summary.",
        "workItemRefs": [{"id": wi_id}]
    }
    
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{ado_org}/{ado_project}/_apis/git/repositories/{ado_repo}/pullrequests?api-version=7.1",
            json=pr_body,
            headers={"Authorization": f"Basic {encode_pat(get_secret('ado-pat'))}"}
        )
```

---

## 5. Context Engineering: Codex Handles It

Another reason the orchestration layer is unnecessary — Codex has built-in context management:

| Concern | Codex Solution |
|---|---|
| Long-running tasks exceed context | Server-side compaction (`compact_threshold` in API config) |
| Large source files | Sub-agent isolation — each agent loads only its module |
| Cross-module knowledge | AGENTS.md hierarchy provides persistent project context |
| Agent coordination overhead | Codex manager consolidates results automatically |
| Multi-language parsing | Built-in tools (ripgrep, file read/write) per sandbox |

The `gpt-5.1-codex-max` model is specifically trained to operate coherently across multiple context windows over millions of tokens in a single task. When a sub-agent approaches its context limit, server-side compaction kicks in automatically.

---

## 6. Porting Your Harness Engine Patterns: Mapping Table

| Harness Engine Pattern | Codex Implementation |
|---|---|
| **Generator-Evaluator separation** | `coder.toml` (sandbox: workspace-write) + `reviewer.toml` (sandbox: read-only) |
| **Ratcheting** | Instruction in `coder.toml`: "revert and retry up to 3x, never commit broken code" |
| **Sprint Contracts** | Work item acceptance criteria passed as task prompt, validated by `reviewer.toml` |
| **TDD enforcement** | Instruction in `coder.toml`: "write tests BEFORE migration code" |
| **Three-layer evaluation** | Instruction in `tester.toml`: unit + integration + contract layers |
| **Self-healing (3 attempts)** | Instruction in `tester.toml` and `coder.toml`: retry protocol with escalation |
| **Session chaining** | Codex server-side compaction handles multi-window sessions natively |
| **Skills directory** | `.codex/agents/` directory with TOML per skill |
| **Hooks** | `config.toml` [hooks] or pre/post scripts in Codex config |
| **Commands (/scaffold, /build, /test)** | Task prompts or AGENTS.md workflow sections |
| **CLAUDE.md** | `AGENTS.md` (identical concept, same purpose) |

---

## 7. Revised Timeline

| Phase | Duration | What |
|---|---|---|
| **Setup** | 2-3 days | Azure AI Foundry + Codex endpoint + ADO service hook |
| **Agent definitions** | 2-3 days | Write 4 TOML agents + AGENTS.md hierarchy |
| **Trigger function** | 1-2 days | Azure Function for ADO webhook + PR creation |
| **Pilot migration** | 1 week | Migrate 2-3 simple modules (leaves of dependency graph) |
| **Iterate and refine** | 1-2 weeks | Tune agent instructions based on pilot results |
| **Full migration** | Ongoing | Agents process remaining modules from ADO backlog |

**Total setup: ~3 weeks** (down from 12 weeks in the original recommendation)

---

## 8. Risks Specific to This Approach

| Risk | Mitigation |
|---|---|
| **Sub-agent conflicts** — concurrent edits by parallel agents | Sequence coder --> tester --> reviewer (don't parallelize write agents on same module) |
| **Token cost** — sub-agents consume more tokens than single-agent | Use `codex-spark` (low-latency, cheaper) for tester; `codex-mini` for coder; reserve `gpt-5.4` for analyzer and reviewer |
| **TOML instruction limits** — complex guardrails may not fit | Split into TOML instructions (agent role) + AGENTS.md (project rules). Agents read both. |
| **Codex sandbox networking** — may not reach ADO repos | Configure Codex with ADO PAT and git remote access in sandbox setup |
| **New platform maturity** — Codex sub-agents GA'd March 2026 | Pilot with simple modules first; have fallback to manual migration for complex modules |

---

## 9. Bottom Line

**You don't need a custom orchestration layer.** Codex's native sub-agent architecture provides everything the Copilot SDK or Open SWE would have given you, but with zero custom orchestration code.

Your Claude Harness Engine is an excellent source of battle-tested patterns (generator-evaluator, ratcheting, TDD-first, sprint contracts, three-layer evaluation). These port directly into Codex as TOML agent definitions and AGENTS.md project guidance — it's a configuration exercise, not a coding exercise.

The total custom code needed is approximately **150 lines** (ADO webhook trigger + PR creation). Everything else is configuration.

### Final Stack

```
Azure AI Foundry (LLMs: codex-mini, gpt-5.4, codex-spark)
  └── Codex CLI (open source, configured with Azure OpenAI endpoint)
       └── Native sub-agents (analyzer, coder, tester, reviewer)
            └── AGENTS.md hierarchy (migration knowledge + guardrails)
                 └── ADO integration (webhook trigger + PR creation)
```

---

## Sources

- [Codex Subagents — OpenAI Developers](https://developers.openai.com/codex/subagents)
- [Custom Instructions with AGENTS.md — OpenAI Developers](https://developers.openai.com/codex/guides/agents-md)
- [Codex Advanced Configuration — OpenAI Developers](https://developers.openai.com/codex/config-advanced)
- [Use Codex with the Agents SDK — OpenAI Developers](https://developers.openai.com/codex/guides/agents-sdk)
- [Awesome Codex Subagents (136+ agent definitions)](https://github.com/VoltAgent/awesome-codex-subagents)
- [Codex on Azure AI Foundry](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/codex)
- [Claude Harness Engine v1](https://github.com/cwijayasundara/claude_harness_eng_v1)
