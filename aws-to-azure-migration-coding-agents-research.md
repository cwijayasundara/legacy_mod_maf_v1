# Cloud Coding Agents for AWS Lambda to Azure Functions Migration

## Deep Research & Strategic Recommendation

**Prepared for:** Financial Industry Platform Migration  
**Date:** April 11, 2026  
**Author:** AI Architecture Advisory

---

## 1. Executive Summary

Your client needs to migrate a multi-language (Java, Python, Node.js, C#) AWS Lambda platform with inter-service dependencies and AWS-native resources (S3, Cosmos DB, RDS Postgres) to Azure Functions. They want to use Azure AI Foundry LLMs, check code into Azure DevOps (ADO), and avoid local developer machines.

After deep research across all viable options, here is the bottom line:

**Recommended approach: A hybrid architecture using OpenAI Codex on Azure AI Foundry as the primary coding agent, augmented with a custom orchestration layer built on the GitHub Copilot SDK or LangChain Open SWE framework, incorporating your existing Claude Harness Engine guardrails as sub-agent skills.**

The rationale follows from three key constraints: (1) the client mandates Azure AI Foundry LLMs, (2) code lives in Azure DevOps, and (3) they want cloud-hosted autonomous agents.

---

## 2. Option Analysis

### 2.1 Option 1: GitHub Copilot in the Cloud with Azure OpenAI LLMs

#### What Works

GitHub Copilot now supports Bring Your Own Key (BYOK) and Bring Your Own Model (BYOM) as of April 2026. You can configure it to use Azure OpenAI models, Anthropic models, and even local models. The Copilot CLI supports this via environment variables, and Copilot Enterprise supports BYOK in chat on GitHub.com and supported IDEs.

The **GitHub Copilot Coding Agent** runs autonomously in the cloud via GitHub Actions. It can research repos, create implementation plans, make code changes, run tests/linters, and open PRs. You trigger it by assigning a GitHub Issue to Copilot.

The **GitHub Copilot SDK** (Python, TypeScript, Go, .NET, Java) lets you build custom agents with sub-agent orchestration, custom tools, and BYOK support for Azure AI Foundry.

#### The Blocker

**The Copilot Coding Agent requires GitHub repositories. Azure DevOps repos are NOT supported.** Microsoft has stated it does not plan to bring Copilot cloud agent capabilities to ADO natively. The Azure Boards integration lets you send work items to Copilot, but the agent operates on GitHub repos, not Azure Repos.

#### Verdict: Partially Viable

If the client is willing to mirror or migrate repos to GitHub (with ADO Boards still managing work items), this becomes the most mature option. If repos must stay in ADO, this path is blocked for the autonomous cloud agent, though the Copilot SDK can still be used to build custom agents that work with ADO repos.

#### Workaround Path

```
Azure Boards (work items) --> GitHub Copilot Agent --> GitHub Repos --> Sync to ADO Repos
```

The Azure DevOps MCP Server (public preview) enables Copilot to access ADO work items, PRs, test plans, and build pipelines, creating a bridge between the two systems.

---

### 2.2 Option 2: Coding Agents from Azure AI Foundry

#### What's Available

Azure AI Foundry Agent Service is now a fully managed, production-capable platform for building, deploying, and scaling AI agents. As of early 2026, it supports:

- No-code prompt agents (portal-defined)
- Code-based hosted agents (Agent Framework, LangGraph, custom code)
- Multi-agent workflows with drag-and-drop orchestration
- Models from OpenAI, DeepSeek, xAI, Meta, Anthropic (Claude Opus 4.6)
- Voice-native agents and Deep Research agents

#### OpenAI Codex on Azure: YES, Fully Supported

This is the strongest finding. **OpenAI Codex runs natively on Azure infrastructure** with:

- Enterprise-grade security, private networking, RBAC
- Data remains within Azure tenant
- Compliance boundary enforcement
- Models: `codex-mini`, `gpt-5`, `gpt-5-mini` via Azure OpenAI endpoints
- Configuration: `base_url: https://YOUR_PROJECT.openai.azure.com/openai/v1`
- API version: `2025-04-01-preview`
- Authentication: API-key based

Codex can auto-generate PRs, refactor files, write tests, and be triggered from GitHub Actions runners, VS Code, or terminal. It runs tasks asynchronously and in parallel with 2M+ weekly active users.

#### Microsoft Agent Framework

Microsoft merged AutoGen and Semantic Kernel into the Microsoft Agent Framework (RC in Feb 2026, 1.0 GA targeted). It includes a **Legacy Modernization Agent** pattern specifically designed for code migration, with agents operating in parallel across discovery, assessment, planning, migration, and code transformation phases.

Azure already has a reference implementation: `Azure-Samples/Legacy-Modernization-Agents` on GitHub.

#### Verdict: STRONGEST OPTION

Codex on Azure AI Foundry meets all three client constraints: uses their Azure AI Foundry LLMs, runs in the cloud, and the underlying Codex CLI is open source and configurable. Combined with the Microsoft Agent Framework for orchestration and the Legacy Modernization Agent pattern, this is the most aligned path.

---

### 2.3 Option 3: Build a Custom Coding Agent

If the above options prove insufficient (e.g., Codex lacks the sub-agent sophistication needed for multi-language migration), here is the framework landscape:

#### Framework Comparison Matrix

| Capability | Copilot SDK | Codex CLI | Claude Agent SDK | Open SWE / DeepAgents | OpenHands | Goose | Aider |
|---|---|---|---|---|---|---|---|
| **Azure OpenAI native** | Yes (BYOK) | Yes (native) | No (Anthropic only) | Configurable | Via OpenRouter | Yes (native) | Yes (native) |
| **Headless cloud execution** | Yes | Yes | Yes | Yes | Yes (K8s) | Yes (Docker) | Yes |
| **Sub-agent orchestration** | Yes (native) | Limited | Yes (native) | Yes (async remote) | Limited | No | No |
| **ADO integration** | Via MCP Server | Manual | No | No | Yes (native) | No | No |
| **Context management** | SDK-managed | Server-side compaction | Session + compaction | Auto-summarization | Container-based | Implicit | Git-based |
| **Multi-language support** | Python/TS/Go/.NET/Java | Python/TS | Python/TS | Python | Python | Rust (CLI) | Python |
| **License** | Proprietary | Apache 2.0 | Proprietary | MIT | MIT | Apache 2.0 | Apache 2.0 |
| **Production readiness** | High | High | High | Medium | High | Medium | High |

#### Top Picks for Custom Build

**1. GitHub Copilot SDK + Azure AI Foundry (Recommended for Custom)**

Best for: Building a sophisticated multi-agent system with enterprise support

- Full BYOK with Azure OpenAI
- Native sub-agent orchestration with custom system prompts and tool restrictions per agent
- Production-tested, available in 5 languages including .NET and Java
- MCP server support for extending capabilities
- Can define Planner, Coder, Reviewer sub-agents with isolated tool sets

**2. LangChain Open SWE + DeepAgents**

Best for: Rapid prototyping with proven SWE patterns

- MIT-licensed, captures patterns from Stripe, Ramp, Coinbase
- Cloud sandboxes, Slack/Linear invocation, sub-agent orchestration, auto PR creation
- DeepAgents provides planning tools (`write_todos`), file operations, shell execution, sub-agent delegation
- Async sub-agents (v0.5.0) for parallel work decomposition
- Built on LangGraph with streaming, persistence, and checkpointing
- Provider-agnostic (should work with Azure OpenAI)

**3. OpenHands (formerly OpenDevin)**

Best for: The most complete out-of-box experience with ADO support

- 70K+ GitHub stars, 490+ contributors, MIT license
- **Only framework with native Azure DevOps Git integration** (ProviderHandler + GitService abstraction)
- Kubernetes-native deployment (v1.6.0)
- 53%+ GitHub issue resolution on SWE-bench Verified
- Sandboxed Docker environments
- LLM-agnostic via OpenRouter or direct API keys

---

## 3. Recommended Architecture

### 3.1 The Hybrid Stack

```
+------------------------------------------------------------------+
|                    AZURE AI FOUNDRY                               |
|  +------------------------------------------------------------+  |
|  |              ORCHESTRATOR AGENT                             |  |
|  |  (Microsoft Agent Framework / Copilot SDK / Open SWE)      |  |
|  |  - Reads ADO work items via Azure DevOps MCP Server        |  |
|  |  - Decomposes migration tasks into sub-agent assignments    |  |
|  |  - Manages dependency graph and execution order             |  |
|  +----+-----------+-----------+-----------+-------------------+  |
|       |           |           |           |                      |
|  +----v----+ +----v----+ +----v----+ +----v----+                |
|  | ANALYZER| | CODER   | | TESTER  | |REVIEWER |                |
|  | AGENT   | | AGENT   | | AGENT   | | AGENT   |                |
|  |         | |         | |         | |         |                |
|  | - Deps  | | - Codex | | - Test  | | - Code  |                |
|  | - AST   | |   on    | |   gen   | |   review|                |
|  | - Biz   | |   Azure | | - E2E   | | - Guard |                |
|  |   logic | | - Multi | | - Integ | |   rails |                |
|  |   extract|   lang  | |         | |         |                |
|  +---------+ +---------+ +---------+ +---------+                |
|                                                                  |
|  +------------------------------------------------------------+  |
|  |          SHARED SERVICES LAYER                              |  |
|  |  - Azure OpenAI (GPT-5 / Codex-mini / o4-mini)            |  |
|  |  - Azure DevOps MCP Server (work items, repos, PRs)       |  |
|  |  - Context Management (compaction + structured notes)      |  |
|  |  - Tree-sitter AST parsing (multi-language)                |  |
|  |  - Ripgrep/Glob for code search                            |  |
|  |  - Dependency graph store (Neo4j or in-memory)             |  |
|  +------------------------------------------------------------+  |
+------------------------------------------------------------------+
```

### 3.2 Phase-by-Phase Migration Workflow

#### Phase 1: Discovery & Analysis (Analyzer Agent)

```
1. Clone all Lambda repos from source control
2. Build dependency graph using Tree-sitter AST parsing across all languages
3. Identify inter-service dependencies (API calls, shared libraries, event bridges)
4. Map AWS resource dependencies (S3, Cosmos DB, RDS, SQS, SNS, etc.)
5. Extract business logic boundaries per module
6. Produce migration manifest: ordered list of modules with dependencies,
   complexity scores, and recommended Azure equivalents
```

**AWS to Azure Resource Mapping:**

| AWS Resource | Azure Equivalent | Migration Complexity |
|---|---|---|
| Lambda Functions | Azure Functions | Medium (runtime + handler changes) |
| S3 Buckets | Azure Blob Storage | Low (SDK swap) |
| Cosmos DB (AWS) | Azure Cosmos DB | Low (already Cosmos) |
| RDS PostgreSQL | Azure Database for PostgreSQL | Low (connection string swap) |
| SQS | Azure Queue Storage / Service Bus | Medium |
| SNS | Azure Event Grid / Service Bus Topics | Medium |
| API Gateway | Azure API Management | Medium |
| EventBridge | Azure Event Grid | Medium |
| DynamoDB | Azure Cosmos DB (Table API) | Medium |
| Step Functions | Azure Durable Functions | High |
| CloudWatch | Azure Monitor / App Insights | Medium |

#### Phase 2: Module-Level Migration (Coder Agent)

For each module (ordered by dependency graph, leaves first):

```
1. Extract business logic from Lambda handler
2. Generate Azure Function scaffolding for target language
3. Replace AWS SDK calls with Azure SDK equivalents
4. Update connection strings and configuration
5. Adapt event triggers (HTTP, Queue, Timer, Blob, etc.)
6. Handle authentication changes (IAM --> Managed Identity)
7. Generate infrastructure-as-code (Bicep/ARM templates)
```

**Language-Specific Considerations:**

- **Java**: AWS Lambda `RequestHandler` --> Azure Functions `@FunctionName` annotation. Maven/Gradle dependency swap.
- **Python**: `lambda_handler(event, context)` --> `@app.function_name()` decorator. boto3 --> azure SDK packages.
- **Node.js**: `exports.handler` --> `module.exports = async function(context, req)`. AWS SDK v3 --> @azure packages.
- **C#**: AWS Lambda `ILambdaContext` --> Azure Functions `FunctionContext`. NuGet package swap. Closest mapping of all languages.

#### Phase 3: Testing & Validation (Tester Agent)

```
1. Generate unit tests for extracted business logic
2. Generate integration tests for Azure resource interactions
3. Run tests in isolated Azure Functions environment
4. Compare outputs against AWS Lambda baseline (shadow testing)
5. Performance benchmarking
```

#### Phase 4: Review & Quality Gates (Reviewer Agent)

```
1. Code review against migration checklist
2. Security scan (credentials, secrets, hardcoded endpoints)
3. Dependency vulnerability scan
4. Architecture compliance validation
5. Raise PR in Azure DevOps with full migration notes
```

---

## 4. Triggering the Agent: From Work Items to PRs

### 4.1 Azure DevOps Trigger Architecture

```
ADO Work Item (User Story / Defect)
    |
    | [Service Hook: work item state changed to "Ready for Agent"]
    v
Webhook Receiver (Azure Function or Container App)
    |
    | [Parse work item, fetch acceptance criteria]
    v
Orchestrator Agent (Azure AI Foundry)
    |
    | [Decompose into sub-tasks]
    v
Coding Agents (parallel execution)
    |
    | [Complete work, push branch]
    v
Create PR in Azure DevOps (via ADO REST API)
    |
    | [Link PR to work item, add agent summary]
    v
Human Review + Merge
    |
    | [PR merge triggers: auto-complete work item]
    v
Done
```

### 4.2 Implementation Options

**Option A: ADO Service Hooks + Azure Container App**

```python
# Webhook receiver (Azure Function)
@app.function_name("agent-trigger")
@app.route(route="webhook/ado", methods=["POST"])
async def trigger_agent(req: func.HttpRequest):
    payload = req.get_json()
    work_item_id = payload["resource"]["workItemId"]
    
    # Fetch full work item details from ADO API
    work_item = await ado_client.get_work_item(work_item_id)
    
    # Dispatch to orchestrator agent
    await orchestrator.run(
        task=work_item["fields"]["System.Description"],
        acceptance_criteria=work_item["fields"]["Microsoft.VSTS.Common.AcceptanceCriteria"],
        repo=work_item["fields"]["Custom.TargetRepo"],
        model="codex-mini"  # Azure OpenAI model
    )
```

**Option B: Azure Pipelines YAML Trigger**

```yaml
# azure-pipelines.yml
trigger: none  # Manual or webhook only

schedules:
  - cron: "0 */2 * * *"  # Check every 2 hours
    displayName: "Agent sweep for ready work items"
    branches:
      include: [main]

steps:
  - task: AzureCLI@2
    displayName: "Run migration agent"
    inputs:
      azureSubscription: "AI-Foundry-Connection"
      scriptType: "bash"
      scriptLocation: "inlineScript"
      inlineScript: |
        python -m migration_agent.orchestrator \
          --ado-org $(System.CollectionUri) \
          --project $(System.TeamProject) \
          --query "SELECT [System.Id] FROM WorkItems WHERE [System.State] = 'Ready for Agent'"
```

**Option C: Power Automate Flow**

Create an automated flow triggered when a work item's state changes to "Ready for Agent", which calls an Azure Function that dispatches the orchestrator.

### 4.3 Making Agents Autonomous

To maximize autonomy while maintaining safety:

1. **Scoped autonomy**: Agents can only create branches and PRs, never merge to main
2. **Guardrailed execution**: Use your Claude Harness Engine's ratcheting pattern (code only improves, failures trigger self-healing up to 3 attempts before escalating)
3. **Human-in-the-loop gates**: PRs require human approval. Agent adds confidence scores and migration notes to PR description
4. **Automatic retry**: If tests fail, agent gets 3 self-healing cycles before creating a "needs-help" work item
5. **Progress reporting**: Agent updates ADO work item with real-time status comments

---

## 5. Context Engineering Strategy

### 5.1 The Core Challenge

Multi-language Lambda migration is a long-running task. A single module migration might require analyzing dozens of files across multiple languages, understanding inter-service contracts, and generating hundreds of lines of replacement code. This will exceed any single context window.

### 5.2 Recommended Context Management Stack

#### Layer 1: Sub-Agent Isolation (Primary Strategy)

Each sub-agent operates in its own context window. The orchestrator delegates focused tasks and receives compressed results.

```
Orchestrator (context: migration manifest + current task)
    |
    +--> Analyzer sub-agent (context: single module's files)
    |    Returns: dependency summary, business logic description
    |
    +--> Coder sub-agent (context: business logic + Azure templates)
    |    Returns: migrated code files
    |
    +--> Tester sub-agent (context: migrated code + test specs)
         Returns: test results + coverage report
```

This is the single most effective technique. Each sub-agent only loads what it needs, processes it, and returns a compressed result.

#### Layer 2: Compaction (For Long Sub-Tasks)

When a sub-agent's conversation approaches the context limit:

- **Server-side compaction** (Codex): Set `compact_threshold` in API config. The server automatically summarizes history while preserving critical task context.
- **Explicit compaction** (custom agents): Periodically summarize the conversation, extract key decisions and findings, and reinitialize with the summary.
- **Structured note-taking**: Agents write findings to persistent files (`/memory/module-analysis-notes.md`) and reload selectively.

#### Layer 3: Smart File Loading (Never Load Everything)

```
WRONG: Load entire codebase into context
RIGHT: Iterative discovery

1. Start with project structure (ls, tree)
2. Identify entry points (Lambda handlers)
3. Follow imports/dependencies with grep/ripgrep
4. Load only relevant files, only relevant sections
5. Use Tree-sitter to extract function signatures without loading bodies
```

### 5.3 OS Tools vs RAG: Use Both

**For code navigation and search: OS Tools (ripgrep, glob, tree-sitter)**

- Ripgrep searches 100K-line codebases in milliseconds with zero preparation
- 3-17x faster than embedding-based retrieval
- 38-41% exact match rate vs 25% for vanilla RAG
- No indexing step, no embedding cost, works immediately on any codebase
- This is what Claude Code, Cursor, and Devin use internally

**For architectural knowledge and migration patterns: Lightweight RAG**

- Pre-index AWS-to-Azure migration documentation
- Embed your client's internal architecture docs and runbooks
- Store migration patterns and known gotchas per language/service combination
- Use as a knowledge base that agents can query, not as the primary code search

**For dependency graphs: Graph database (optional)**

- Neo4j or in-memory graph for storing extracted inter-service dependencies
- Agents query the graph to determine migration ordering
- Visualize dependency chains for human review

### 5.4 Handling Large Source Files

For files that exceed context limits:

1. **Tree-sitter AST extraction**: Parse the file, extract function/class signatures and their line ranges. Load only the relevant function bodies on demand.
2. **Chunked processing**: Process file in logical chunks (class by class, function by function) using AST boundaries, not arbitrary line splits.
3. **Summary-first approach**: Generate a structural summary of the file (classes, methods, imports, key patterns) that fits in context. Then deep-dive into specific sections as needed.
4. **Code-specific chunking (cAST)**: Use Abstract Syntax Trees to chunk while maintaining syntactic integrity. Recursively break large AST nodes into smaller chunks and merge sibling nodes while respecting size limits.

---

## 6. Integrating Your Claude Harness Engine

Your existing `claude_harness_eng_v1` scaffolding has valuable patterns that should be ported into the migration agent system:

### 6.1 Patterns to Reuse

| Harness Engine Pattern | Migration Agent Application |
|---|---|
| Generator-Evaluator separation | Coder agent (generator) + Reviewer agent (evaluator) |
| Ratcheting (monotonic improvement) | Migration quality gates: code only moves forward |
| Sprint Contracts | Per-module migration contracts: done criteria before coding |
| TDD enforcement | Generate tests for business logic BEFORE migrating code |
| Three-layer evaluation (API, Playwright, Vision) | API tests + integration tests + deployment validation |
| Session chaining | Multi-context-window migration sessions |
| Self-healing (3 attempts, 10 error categories) | Agent retry with escalation for migration failures |

### 6.2 Porting Strategy

Since the client uses Azure AI Foundry (not Claude directly), you cannot use the Claude Harness Engine as-is. Instead:

1. **Extract the skill definitions** (scaffold, build, evaluate, test, deploy) as language-agnostic prompt templates
2. **Port guardrails** as validation rules in the orchestrator: TDD-first, ratcheting, sprint contracts
3. **Implement the generator-evaluator pattern** using Copilot SDK sub-agents or Open SWE's async sub-agent architecture
4. **Adapt commands** (`/scaffold`, `/build`, `/evaluate`, `/test`, `/deploy`) as agent workflow steps triggered by work item state transitions

---

## 7. Concrete Implementation Recommendation

### 7.1 Recommended Stack

```
Layer                  | Technology                        | Why
-----------------------|-----------------------------------|----------------------------------
LLM Provider           | Azure OpenAI (Codex-mini, GPT-5) | Client requirement
Agent Runtime          | Codex CLI on Azure + Custom       | Native Azure, open source
                       | orchestration                     |
Orchestration          | Copilot SDK (.NET/Python) OR      | Sub-agents, BYOK, production-
                       | LangChain Open SWE                | tested
Compute                | Azure Container Apps              | Serverless, scales to zero
Code Search            | Ripgrep + Tree-sitter             | Fast, proven, no indexing
Source Control         | Azure DevOps Repos                | Client requirement
Work Items             | Azure Boards                      | Client requirement
Trigger                | ADO Service Hooks + Azure         | Event-driven, near real-time
                       | Functions                         |
CI/CD                  | Azure Pipelines                   | Native ADO integration
Knowledge Base         | Azure AI Search (for migration    | Migration docs + patterns
                       | patterns)                         |
Dependency Graph       | In-memory (NetworkX) or Neo4j     | Module ordering
```

### 7.2 Build vs Buy Decision

| Approach | Effort | Risk | Fit |
|---|---|---|---|
| **Codex on Azure AI Foundry** (Option 2) | Low (weeks) | Low | High -- native Azure, uses their LLMs |
| **Copilot SDK custom agent** (Option 3a) | Medium (1-2 months) | Medium | High -- full control, BYOK, sub-agents |
| **Open SWE + DeepAgents** (Option 3b) | Medium (1-2 months) | Medium | Medium -- MIT, proven patterns, needs Azure config |
| **OpenHands** (Option 3c) | Low-Medium | Medium | High for ADO -- only native ADO Git support |
| **Full custom from scratch** | High (3-6 months) | High | Highest flexibility, highest cost |

### 7.3 Phased Delivery Plan

**Phase 0: Foundation (Weeks 1-2)**

- Set up Azure AI Foundry with Codex-mini and GPT-5 models
- Deploy Codex CLI in Azure Container App
- Configure Azure DevOps MCP Server
- Set up ADO Service Hooks for agent triggering
- Validate Codex can read/write to ADO repos

**Phase 1: Analyzer Agent (Weeks 3-4)**

- Build dependency graph extraction using Tree-sitter (supports all 4 languages)
- Implement business logic extraction per module
- Generate migration manifest with ordering and complexity scores
- Human review gate: approve migration plan

**Phase 2: Coder Agent (Weeks 5-8)**

- Implement per-language migration templates (Java, Python, Node.js, C#)
- AWS SDK to Azure SDK replacement patterns
- Lambda handler to Azure Function handler conversion
- Infrastructure-as-code generation (Bicep)
- Integrate guardrails from your Harness Engine (TDD-first, ratcheting)

**Phase 3: Tester + Reviewer Agents (Weeks 9-10)**

- Auto-generate unit and integration tests
- Shadow testing against AWS baselines
- Code review automation
- PR creation with migration notes and confidence scores

**Phase 4: Autonomous Pipeline (Weeks 11-12)**

- End-to-end: ADO work item --> agent --> PR --> human review
- Self-healing and retry logic
- Progress reporting back to ADO work items
- Monitoring and alerting dashboard

---

## 8. Key Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Context window exhaustion on complex modules | Agent loses track of migration state | Sub-agent isolation + compaction + structured notes |
| Multi-language AST parsing inconsistencies | Incorrect dependency graphs | Use Tree-sitter (supports 25+ languages) + manual review of Phase 1 output |
| Azure OpenAI rate limits during parallel migration | Slow agent execution | Provisioned throughput + queue-based throttling |
| Agent generates incorrect Azure SDK usage | Runtime failures | TDD-first pattern: generate and run tests before committing |
| Inter-service dependencies break during phased migration | Partial system failure | Migrate leaves first (dependency order) + feature flags + shadow traffic |
| ADO repo access from containerized agents | Authentication failures | Managed Identity + Azure DevOps PAT (rotate monthly) |
| Cost overrun from LLM token usage | Budget exceeded | Token budgets per module + cost monitoring alerts |

---

## 9. Open Source Coding Agents: Detailed Assessment

### 9.1 Best for This Use Case

**OpenHands** stands out as the only open-source framework with native Azure DevOps Git integration. Its three-layer architecture (ProviderHandler, GitService, concrete implementations) includes specific ADO URL-encoding handling. With Kubernetes support (v1.6.0) and 53%+ issue resolution rates, it is the most deployment-ready option for an ADO-centric workflow.

**LangChain Open SWE / DeepAgents** offers the most sophisticated sub-agent architecture with async remote agents and isolated context windows. The planning tools (`write_todos`), auto-summarization, and output-to-file pattern align well with long-running migration tasks. MIT-licensed and captures real patterns from Stripe/Ramp/Coinbase engineering.

**Block's Goose** has explicit Azure OpenAI support and MCP connectivity (70+ extensions), but lacks native sub-agent orchestration. Best as a component agent within a larger system.

**Aider** has native Azure OpenAI support (`aider --model azure/<deployment>`) and excellent git integration, but is designed for human-in-the-loop terminal use, not autonomous cloud execution.

### 9.2 Agents to Avoid for This Use Case

- **Claude Agent SDK**: Locked to Anthropic models. Cannot use Azure OpenAI natively. The LiteLLM proxy workaround is fragile for production.
- **SWE-Agent**: No documented Azure support. Focused on AWS Fargate and Modal runtimes.
- **Cline/Continue**: IDE-focused, not designed for headless cloud deployment (Cline's CLI 2.0 is emerging but not mature).

---

## 10. Context Engineering: Lessons from Claude Code and Codex

### 10.1 What Claude Code Teaches Us

Claude Code's architecture reveals key patterns now considered best practice:

1. **Three persistent context layers**: Project instructions (CLAUDE.md), auto-saved learnings (MEMORY.md), and sub-agent isolation. Replicate this with per-project migration configs, persistent findings files, and isolated sub-agent contexts.

2. **Ripgrep over RAG**: Claude Code uses ripgrep for code search, not vector embeddings. For a multi-language codebase, ripgrep's language-agnostic regex search is superior to language-specific embeddings.

3. **Tool-use over retrieval**: Rather than pre-loading context, Claude Code discovers context on-demand using tools (grep, glob, read). This "pull" model is more token-efficient than "push" (RAG).

### 10.2 What Codex Teaches Us

OpenAI's Codex architecture introduces server-side compaction:

1. **Automatic compaction**: When context approaches limits, the server compresses history while preserving critical task state. The compacted representation is opaque (not human-readable) but enables coherent multi-window sessions.

2. **GPT-5.1-Codex-Max** is specifically trained for multi-context-window operation, maintaining coherence across millions of tokens in a single task.

3. **API-level support**: `context_management` with `compact_threshold` in API requests enables automatic compaction without custom code.

### 10.3 Practical Context Budget

For a typical Lambda module migration:

```
Context Budget Allocation (128K token window):
- System prompt + migration instructions:  ~4K tokens
- Module dependency context:                ~2K tokens
- Source files (Lambda handler + deps):     ~20-40K tokens
- Azure Function templates + patterns:      ~10K tokens
- Test specifications:                      ~5K tokens
- Conversation history + reasoning:         ~40-60K tokens
- Safety margin:                            ~20K tokens
```

For modules exceeding this budget, the sub-agent isolation pattern is mandatory.

---

## 11. Decision Matrix: Final Recommendation

| Client Requirement | Option 1 (Copilot Cloud) | Option 2 (Codex on Foundry) | Option 3 (Custom Build) |
|---|---|---|---|
| Azure AI Foundry LLMs | Yes (BYOK) | Yes (native) | Yes (configurable) |
| Azure DevOps repos | NO (GitHub only) | Yes (Codex CLI) | Yes (OpenHands/custom) |
| Cloud-hosted (no local) | Yes (GitHub Actions) | Yes (Container Apps) | Yes (K8s/Container Apps) |
| Autonomous from work items | Yes (Issues) | Custom trigger needed | Custom trigger needed |
| Multi-language support | Yes | Yes | Framework-dependent |
| Sub-agent orchestration | Yes (SDK) | Limited | Yes (Open SWE/Copilot SDK) |
| Production maturity | Highest | High | Medium |
| Time to value | Fastest (if on GitHub) | Fast (weeks) | Medium (1-3 months) |

### Final Recommendation

**Primary: Deploy Codex on Azure AI Foundry** as the core coding agent, running in Azure Container Apps. Use the open-source Codex CLI configured with the client's Azure OpenAI endpoints. This gives you a production-grade coding agent running entirely within Azure, using their own LLMs.

**Orchestration: Build a thin orchestration layer** using the GitHub Copilot SDK (for sub-agent patterns) or LangChain Open SWE (for async sub-agent isolation). This layer handles work item intake from ADO, task decomposition, agent coordination, and PR creation.

**Guardrails: Port your Claude Harness Engine patterns** (generator-evaluator, ratcheting, TDD-first, sprint contracts) as orchestrator-level rules and sub-agent system prompts. These become the quality backbone of the migration pipeline.

**ADO Integration: Use ADO Service Hooks** to trigger the orchestrator when work items reach "Ready for Agent" state. The orchestrator dispatches sub-agents, and the results are committed as PRs in ADO repos via the ADO REST API.

This hybrid approach gives the client the maximum autonomy and quality while staying entirely within their Azure AI Foundry ecosystem and Azure DevOps workflow.

---

## Appendix A: Key References

- GitHub Copilot BYOK: github.blog/changelog/2026-04-07-copilot-cli-now-supports-byok-and-local-models
- GitHub Copilot SDK: github.com/github/copilot-sdk
- Azure AI Foundry Agent Service: learn.microsoft.com/en-us/azure/foundry/agents/overview
- Codex on Azure: learn.microsoft.com/en-us/azure/foundry/openai/how-to/codex
- OpenAI Codex CLI: github.com/openai/codex
- LangChain Open SWE: blog.langchain.com/open-swe-an-open-source-framework-for-internal-coding-agents
- LangChain DeepAgents: github.com/langchain-ai/deepagents
- OpenHands: github.com/OpenHands/OpenHands
- Block's Goose: github.com/block/goose
- Azure Legacy Modernization Agents: github.com/Azure-Samples/Legacy-Modernization-Agents
- Microsoft Agent Framework: learn.microsoft.com/en-us/azure/foundry
- Context Engineering (Anthropic): anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Context Engineering (Martin Fowler): martinfowler.com/articles/exploring-gen-ai/context-engineering-coding-agents.html
- Claude Code Architecture: claude-code-from-source.com/ch01-architecture
- OpenAI Compaction: developers.openai.com/api/docs/guides/compaction
- GrepRAG research: arxiv.org/html/2601.23254v2
- Claude Harness Engine: github.com/cwijayasundara/claude_harness_eng_v1

## Appendix B: Azure DevOps Agent Trigger - Sample Implementation

```python
"""
ADO Work Item --> Agent Trigger
Azure Function that receives ADO Service Hook webhooks
and dispatches coding agents via Azure AI Foundry
"""
import azure.functions as func
import json
import httpx
from azure.identity import DefaultAzureCredential
from azure.ai.foundry import AgentClient

app = func.FunctionApp()

@app.function_name("migration-agent-trigger")
@app.route(route="webhook/ado-workitem", methods=["POST"])
async def handle_workitem_update(req: func.HttpRequest) -> func.HttpResponse:
    payload = req.get_json()
    
    # Extract work item details
    work_item_id = payload["resource"]["id"]
    state = payload["resource"]["fields"]["System.State"]
    
    if state != "Ready for Agent":
        return func.HttpResponse("Ignored: not ready for agent", status_code=200)
    
    # Fetch full work item from ADO API
    ado_org = "https://dev.azure.com/YOUR_ORG"
    ado_pat = get_secret("ado-pat")  # From Azure Key Vault
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{ado_org}/_apis/wit/workitems/{work_item_id}?$expand=all&api-version=7.1",
            headers={"Authorization": f"Basic {encode_pat(ado_pat)}"}
        )
        work_item = resp.json()
    
    # Dispatch to orchestrator agent
    credential = DefaultAzureCredential()
    agent_client = AgentClient(
        endpoint="https://YOUR_PROJECT.openai.azure.com",
        credential=credential
    )
    
    migration_task = {
        "title": work_item["fields"]["System.Title"],
        "description": work_item["fields"]["System.Description"],
        "acceptance_criteria": work_item["fields"].get(
            "Microsoft.VSTS.Common.AcceptanceCriteria", ""
        ),
        "module": work_item["fields"].get("Custom.TargetModule", ""),
        "source_language": work_item["fields"].get("Custom.SourceLanguage", ""),
        "work_item_id": work_item_id
    }
    
    # Kick off async agent execution
    await agent_client.create_run(
        agent_id="migration-orchestrator",
        input=json.dumps(migration_task),
        model="codex-mini"
    )
    
    return func.HttpResponse(
        f"Agent dispatched for work item {work_item_id}",
        status_code=202
    )
```

## Appendix C: Glossary

| Term | Definition |
|---|---|
| **ADO** | Azure DevOps |
| **BYOK/BYOM** | Bring Your Own Key / Bring Your Own Model |
| **Compaction** | Summarizing conversation history to free context window space |
| **Context Window** | Maximum tokens an LLM can process in a single request |
| **MCP** | Model Context Protocol - standard for connecting AI agents to tools |
| **Ratcheting** | Pattern ensuring code quality only improves, never degrades |
| **SWE-bench** | Benchmark for evaluating coding agents on real GitHub issues |
| **Tree-sitter** | Incremental parser for building ASTs across 25+ languages |
| **Sub-agent** | Specialized agent spawned by an orchestrator for a focused task |
