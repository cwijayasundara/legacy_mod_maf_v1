# AGENTS.md — Copilot Harness: AWS Lambda to Azure Functions Migration

## Project Context
Multi-language (Java, Python, Node.js, C#) AWS Lambda platform migration
to Azure Functions. Driven by work items in Azure DevOps.

Copilot CLI's built-in sub-agents (Explore, Task, Review, Plan) handle
automatic delegation. This file provides migration-specific guidance.

## Migration Principles
1. **TDD-First**: Tests before code. Always.
2. **Ratcheting**: Quality only moves forward. Coverage never drops below `config/state/coverage-baseline.txt`.
3. **Generator-Evaluator Separation**: The agent that writes code does not evaluate it.
4. **Leaves First**: Migrate modules with no inbound dependencies first.
5. **Business Logic Preservation**: Migrated function MUST behave identically.
6. **Three-Layer Evaluation**: Unit → Integration → Contract validation.
7. **Sprint Contracts**: Machine-readable done-criteria agreed before coding starts.
8. **Learned Rules**: Mistakes captured and injected to prevent repetition.

## Workflow per Module

### Step 0: Read Context
Before any work, read:
- `config/program.md` — human steering constraints
- `config/state/learned-rules.md` — ALL rules (prevents repeated mistakes)
- `config/state/migration-progress.txt` — context from prior runs
- `config/state/coverage-baseline.txt` — coverage floor

### Step 1: Analyze
Read Lambda source, map AWS dependencies, score complexity.
Output: `migration-analysis/{module}/analysis.md`

### Step 2: Sprint Contract
Propose done-criteria as JSON (`migration-analysis/{module}/sprint-contract.json`).
Schema: `config/templates/sprint-contract.json`

### Step 3: Migrate (TDD-First)
Write tests FIRST, then migrate code, then generate Bicep template.
Output: `src/azure-functions/{module}/`, `infrastructure/{module}/main.bicep`

### Step 4: Evaluate (3-Layer)
Unit tests → Integration (emulator) → Contract validation.
On failure: write structured `eval-failures.json`, retry up to 3x.
Output: `migration-analysis/{module}/test-results.md`

### Step 5: Review (8-Point Gate)
Business logic, no AWS artifacts, Azure best practices, error handling,
configuration, security, performance, infrastructure.
Output: `migration-analysis/{module}/review.md`

### Step 6: Security Review
OWASP top 10 scan. BLOCK findings must be fixed.
Output: `migration-analysis/{module}/security-review.md`

## AWS → Azure Resource Mapping
| AWS Service | Azure Equivalent | Azure SDK Package |
|------------|-----------------|-------------------|
| S3 | Azure Blob Storage | azure-storage-blob |
| SQS | Queue Storage / Service Bus | azure-storage-queue |
| SNS | Event Grid / Service Bus Topics | azure-eventgrid |
| DynamoDB | Cosmos DB | azure-cosmos |
| RDS PostgreSQL | Azure Database for PostgreSQL | psycopg2 |
| CloudWatch | Azure Monitor + App Insights | azure-monitor |
| Secrets Manager | Azure Key Vault | azure-keyvault-secrets |
| IAM Roles | Managed Identity | azure-identity |
| API Gateway | API Management / HTTP Triggers | azure-functions |
| Step Functions | Durable Functions | azure-functions-durable |

## Quality Gates (7-Gate Ratchet)
1. Analysis complete with complexity score
2. Sprint contract negotiated
3. Tests written and passing
4. Migration complete, all tests green
5. Contract validation passed
6. Review approved (score >= 70)
7. Security review passed (no BLOCK findings)

## Code Quality Principles
Follow `.copilot/quality-principles.md` — 6 mandatory rules.
Follow `.copilot/architecture.md` — layered dependency enforcement.
