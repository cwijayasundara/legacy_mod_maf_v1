# AGENTS.md — Clodex Harness: AWS Lambda to Azure Functions Migration

## Project Context
This is a multi-language (Java, Python, Node.js, C#) AWS Lambda platform being migrated
to Azure Functions. The migration is driven by work items in Azure DevOps (ADO).

Each Lambda module is analyzed, migrated, tested, and reviewed by specialized Codex sub-agents
before a pull request is created in ADO.

## Migration Principles (from Harness Engine)
1. **TDD-First**: Tests before code. Always. No exceptions.
2. **Ratcheting**: Quality only moves forward. Coverage never drops below `state/coverage-baseline.txt`.
3. **Generator-Evaluator Separation**: The coder writes code, the tester evaluates, the reviewer gates. No self-evaluation.
4. **Leaves First**: Migrate modules with no inbound dependencies first (see `depends-on` in modules.tsv).
5. **Business Logic Preservation**: The migrated function MUST behave identically to the original.
6. **Three-Layer Evaluation**: Unit tests → Integration tests → Contract validation.
7. **Sprint Contracts**: Machine-readable done-criteria agreed before coding starts.
8. **Learned Rules**: Mistakes are captured and injected into all agents to prevent repetition.
9. **Structured Failures**: Error reports use classified categories for targeted self-healing.

## Persistent Context Files (Read Every Iteration)
Agents MUST read these files before starting any task:
| File | Purpose | Who Reads |
|------|---------|-----------|
| `program.md` | Human steering — constraints, overrides, stopping criteria | All agents |
| `state/learned-rules.md` | Monotonic knowledge base — prevents repeated mistakes | All agents |
| `state/migration-progress.txt` | Session chaining — recover context from prior runs | All agents |
| `state/coverage-baseline.txt` | Coverage ratchet floor — never drop below | Coder, Tester |
| `state/failures.md` | Raw failure data — for pattern extraction | Tester |

## Agent Workflow per Module

### Step 0: Sprint Contract Negotiation (2-Call Handshake)
```
CODER proposes sprint contract → writes migration-analysis/{module}/sprint-contract.json
TESTER finalizes contract → adds missing checks, removes invalid ones → contract is IMMUTABLE
```
Both sides agree on exactly what PASS means before any code is written.
Schema: `templates/sprint-contract.json`

### Step 1-4: Migration Pipeline
```
1. ANALYZER (read-only, model: o4)
   └── Reads Lambda source → produces analysis.md with dependency map + complexity score
   └── Reads learned-rules.md to check for known patterns

2. CODER (workspace-write, model: codex-mini) — GENERATOR role
   └── Proposes sprint contract
   └── Reads analysis.md → writes tests FIRST → migrates code → generates Bicep template
   └── Does NOT run tests (tester does) or review code (reviewer does)

3. TESTER (workspace-write, model: o4-mini) — EVALUATOR role
   └── Finalizes sprint contract
   └── Runs three-layer evaluation (unit, integration, contract)
   └── Writes structured failure reports (eval-failures.json) on failure
   └── Enforces coverage ratchet
   └── Extracts learned rules from repeated failures

4. REVIEWER (read-only, model: o4) — QUALITY GATE
   └── Reviews against 8-point checklist + sprint contract
   └── Writes review.md with APPROVE/CHANGES_REQUESTED/BLOCKED
   └── Updates migration-progress.txt and program.md pipeline status
```

Agents execute SEQUENTIALLY for a given module (no parallel writes to the same module).
Multiple modules CAN be processed in parallel (each gets its own agent pipeline).

## Quality Gates (6-Gate Ratchet)
1. **Gate 1 — Analysis Complete**: Analyzer produced `analysis.md` with complexity score
2. **Gate 2 — Tests Written**: Unit tests exist and pass against original Lambda code
3. **Gate 3 — Migration Complete**: Azure Function code written, all tests green
4. **Gate 4 — Integration Validated**: Emulator-based integration tests pass
5. **Gate 5 — Contract Verified**: Input/output schemas match original (sprint contract checks)
6. **Gate 6 — Review Approved**: Reviewer score >= 70, no blocking issues, Bicep template valid

A module advances to PR creation ONLY after all 6 gates pass.

## Enforcement Hooks
| Hook | Trigger | Behavior |
|------|---------|----------|
| `post-task-lint.js` | After each task | Lint + auto-fix |
| `pre-commit-gate.js` | Before commit | Tests + lint + types + architecture + review |
| `detect-secrets.js` | On file write | Block hardcoded secrets |
| `check-architecture.js` | On file write | Block upward layer imports |
| `check-function-length.js` | On file write | Warn >50, block >100 lines |
| `check-file-length.js` | On file write | Warn >200, block >300 lines |
| `typecheck.js` | On file write | mypy/tsc type checking |

## Code Quality Principles (from Harness Engine)
All agents MUST follow these principles. See `.codex/quality-principles.md` for details.
1. **Small Modules** — 300-line block, 200-line warn
2. **Static Typing** — Full type hints, zero `any`
3. **Functions Under 50 Lines** — Decompose into named sub-functions
4. **Single Owner for State Mutations** — Repository pattern
5. **Explicit Error Handling** — Typed exceptions, structured responses
6. **No Dead Code** — Every line traces to a requirement

## Architecture Enforcement
Strict layered imports: Types -> Config -> Repository -> Service -> API -> UI.
See `.codex/architecture.md`. Hook blocks upward imports.

## Security Review
The `security-reviewer` agent scans for OWASP top 10 vulnerabilities.
Runs after the migration-reviewer. BLOCK findings must be fixed before PR.

## Self-Healing Protocol (10 Error Categories)
When a gate fails, the tester writes a structured failure report (`eval-failures.json`)
with one of 10 classified error categories. The coder reads the report and applies
the category-specific fix strategy from `program.md`.

After 3 failed attempts:
1. Write `blocked.md` with root cause analysis
2. Append to `state/failures.md`
3. If same error appeared 2+ times across modules → add to `state/learned-rules.md`

## Directory Structure

The `.codex/` directory is the scaffolding package. When dropped into a target repo,
Codex reads it automatically. The agents create output directories at runtime.

```
.codex/                              ← Scaffolding (checked into target repo)
├── agents/                          TOML agent definitions
├── config.toml                      Models, hooks, protected paths
├── program.md                       Human steering (edit mid-run)
├── scripts/                         CLI runners + hooks
├── templates/                       Sprint contract + failure report schemas
└── state/                           Learned rules, progress, coverage baseline

AGENTS.md                            ← Root guidance (Codex reads from repo root)

# Created at runtime by agents:
migration-analysis/{module}/         Agent outputs (analysis, tests, review)
src/azure-functions/{module}/        Migrated Azure Function code
infrastructure/{module}/             Bicep templates
```

## AWS → Azure Resource Mapping (Global Reference)
| AWS Service | Azure Equivalent | Azure SDK Package |
|------------|-----------------|-------------------|
| S3 | Azure Blob Storage | azure-storage-blob |
| SQS | Azure Queue Storage / Service Bus | azure-storage-queue / azure-servicebus |
| SNS | Event Grid / Service Bus Topics | azure-eventgrid / azure-servicebus |
| DynamoDB | Cosmos DB | azure-cosmos |
| RDS PostgreSQL | Azure Database for PostgreSQL | psycopg2 (connection string swap) |
| CloudWatch | Azure Monitor + App Insights | azure-monitor / opencensus |
| Secrets Manager | Azure Key Vault | azure-keyvault-secrets |
| IAM Roles | Managed Identity | azure-identity (DefaultAzureCredential) |
| API Gateway | API Management / HTTP Triggers | azure-functions |
| Step Functions | Durable Functions | azure-functions-durable |
| EventBridge | Event Grid | azure-eventgrid |
| CloudFormation | Bicep / ARM | N/A (IaC) |

## Commit Conventions
- All commits reference the work item: `[WI-{id}] Migrate {module} to Azure Functions`
- PR descriptions include: what was migrated, what changed, confidence score from reviewer
- Blocked modules get a `blocked.md` with detailed root cause analysis

## Example
A Python Lambda example is provided in `example/lambda/` for testing the pipeline.
See `example/README.md` for usage instructions.
