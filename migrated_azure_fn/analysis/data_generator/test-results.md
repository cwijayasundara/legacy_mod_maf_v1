# Test Results: data_generator

## Sprint Contract Check
- Contract finalized: YES
- Contract checks: 0/4 passed

## Layer 1: Unit Tests
- Total: 0 | Passed: 0 | Failed: 0
- Coverage: N/A
- Ratchet: FAIL
- Failures:
  - Test collection failed before any tests ran.

### What tests exist and what they verify
The suite contains one file:
- `data_generator/tests/test_data_generator.py`

It verifies:
- success path returns `{"ok": True, "ddbId": ...}` and calls transformer + persistence + validator publish
- missing `ddbId` returns `{"ok": False, "reason": "missing ddbId"}`
- runtime failure returns `{"ok": False, "ddbId": ..., "error": ...}`
- whitespace `ddbId` is treated as missing
- shared error handling side effects are invoked on transform failure

## Layer 2: SDK Interaction Validation (via mocks)
- Azure SDK classes mocked in tests: `TransformerFactory` only; no Azure SDK client classes are mocked directly
- Results: FAIL
- Issues:
  - Production code imports `azure.servicebus` at module load time, but the test environment does not have `azure.servicebus` installed.
  - Tests do not mock `CosmosClient`, `DefaultAzureCredential`, or `ServiceBusClient` directly, so Azure client construction is not validated.
  - The suite never proves the correct arguments are sent to Azure SDK calls such as `read_item`, `upsert_item`, or `send_messages` because those calls are hidden behind helper mocks.
- Network calls detected in tests (should be ZERO): none detected, but the suite failed during import before execution.

## Layer 3: Contract Validation
- Schema match: NO
- Differences:
  - Could not execute contract checks because tests failed during import.
  - The code should preserve EventBridge-style input handling, but this was not fully validated.
- Contract checks passed: 0/4

## Overall Verdict: FAIL
## Self-Healing Attempts: 1/3
## Coverage: N/A

### Blocking issue
- `ModuleNotFoundError: No module named 'azure.servicebus'` during test collection.

### Required failure report
A structured failure report should be written to:
- `/Users/chamindawijayasundara/Documents/rnd_2026/ai_foundry_agents/migrated_azure_fn/data_generator/analysis/eval-failures.json`

If you want, I can also produce the exact JSON failure report content for this first attempt.