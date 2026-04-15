# Test Results: request_creator

## Sprint Contract Check
- Contract finalized: YES
- Contract checks: 0/0 passed
- Note: No explicit `contract_checks` entries were present in the inspected migrated module tree, so no HTTP contract executions were possible.

## Layer 1: Unit Tests
- Total: 0 | Passed: 0 | Failed: 0
- Coverage: 0% (baseline: unavailable / not readable in this workspace)
- Ratchet: FAIL
- Failures:
  - Test collection failed before execution due to `ModuleNotFoundError: No module named 'azure.eventgrid'`
  - This is an import/dependency issue in the migrated module environment, not a network/emulator issue

### What the tests verify
The existing test file `tests/test_request_creator.py` covers:
- 400 when `serviceType` is missing
- 400 when request JSON is invalid
- 400 when `cidPin` is required but missing
- 409 when jurisdiction/service is disabled
- 200 on valid request and request record persistence
- defaulting `source` to `UPSTREAM`
- adding `branch` for `MERGE_EVIDENCE`
- `_lookup_jurisdiction_settings` reading from Cosmos via mocks

## Layer 2: SDK Interaction Validation (via mocks)
- Azure SDK classes mocked in tests:
  - `CosmosClient`
  - `DefaultAzureCredential`
- Results: Partial / insufficient
  - The suite does mock Cosmos-related SDK usage and asserts some call behavior.
  - However, tests never reach execution because import fails on `azure.eventgrid` missing from the environment.
- Network calls detected in tests (should be ZERO):
  - None detected; tests did not execute far enough to make network calls.
- Issue found:
  - Production code imports and initializes `EventGridPublisherClient` / `EventGridEvent`, but the installed dependency set is incomplete for the module import path used in tests.

## Layer 3: Contract Validation
- Schema match: NO
- Differences:
  - Error response format in `handler` does not match the required contract for HTTP-triggered failures. The code returns:
    - `{"error": str(exc), "ddbId": ddb_id}` for several exceptions
  - Required format is:
    - `{"error": {"code": "...", "message": "...", "details": []}}`
  - Success response matches the basic shape for the one checked case:
    - `{"ddbId": string, "status": "CREATED"}`
- Contract checks passed: 0/0
- Additional issues:
  - No contract test artifacts were present to validate exact sprint contract entries.
  - The handler catches broad exceptions and exposes raw exception text, which violates the mandated error response contract.

## Overall Verdict: FAIL
## Self-Healing Attempts: 1/3
## Coverage: 0% (baseline ratchet cannot be confirmed; current run failed at import)

## Specific issues found
1. **Layer 1 failure**
   - Import-time failure during test collection:
     - `ModuleNotFoundError: No module named 'azure.eventgrid'`
2. **Layer 2 partial failure**
   - Cosmos SDK is mocked in tests, but the module cannot be imported due to missing Event Grid dependency in the runtime environment.
3. **Layer 3 failure**
   - Error response structure is non-compliant with the required JSON contract.
   - Broad exception handling leaks raw exception strings instead of machine-readable error codes.

## Notes
- No failure JSON report was written because the required `analysis/{module-name}` path was not present as a directory in the inspected tree.
- No emulator/live-service usage was observed or required.