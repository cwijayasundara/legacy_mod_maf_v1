# Program — Human Steering Document
#
# This file is read by the Codex manager agent at the START of every migration.
# Edit this file to steer agent behavior mid-run without restarting.
#
# Changes take effect on the NEXT module migration (not mid-module).

## Current Directive
Migrate all modules listed in .codex/scripts/modules.tsv from AWS Lambda to Azure Functions.
Follow the AGENTS.md workflow and quality gates.

## Constraints
- TDD-first: tests BEFORE code. No exceptions.
- Ratcheting: coverage never drops below state/coverage-baseline.txt
- Maximum self-healing attempts per gate: 3
- Maximum total iterations per module: 10
- Coverage floor: 80%
- Coverage target: 100% of meaningful business logic
- Reviewer confidence threshold: 70/100

## Stopping Criteria
Stop the migration pipeline if ANY of these occur:
1. All modules in modules.tsv are completed (success)
2. 3 consecutive modules are BLOCKED (systemic issue — escalate to human)
3. Coverage drops below baseline (ratchet violation — investigate)
4. 50 total iterations reached across all modules (budget exceeded)

## Module-Specific Overrides
# Uncomment and edit to override behavior for specific modules:
# [order-processor]
# skip_integration_tests = true  # Reason: no Azurite available in CI yet
# max_attempts = 5               # Reason: complex module, needs more tries

## Self-Healing Policy
When a gate fails, the agent should apply a category-specific fix strategy:
| Error Category | Strategy |
|---------------|----------|
| import_error | Check Azure SDK package name; verify requirements.txt/package.json |
| sdk_mismatch | Re-read AWS→Azure mapping in AGENTS.md; check method signatures |
| schema_mismatch | Diff original Lambda response vs Azure Function response |
| missing_handler | Verify function entry point matches host.json/function.json |
| auth_failure | Check DefaultAzureCredential setup; verify local.settings.json |
| connection_error | Verify emulator is running; check connection string format |
| timeout | Increase timeout in host.json; check for blocking I/O |
| assertion_error | Compare test expectation with actual Azure Function behavior |
| configuration_error | Verify env vars in local.settings.json match what code reads |
| runtime_error | Read stack trace; check language-specific AGENTS.md for patterns |

## Pipeline Status
# Updated by the agent after each module completes:
# | Module | Status | Gates Passed | Coverage | Reviewer Score |
# |--------|--------|-------------|----------|----------------|
# | (populated during execution) |
