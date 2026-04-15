# Test Results: validation

## Sprint Contract Check
- Contract finalized: NO
- Contract checks: 0/Y passed

## Layer 1: Unit Tests
- Total: 0 | Passed: 0 | Failed: 0
- Coverage: 0% (baseline: not verified)
- Ratchet: FAIL
- Failures:
  - Test collection failed due to `ModuleNotFoundError: No module named 'azure.servicebus'`
  - No unit tests executed successfully

## Layer 2: SDK Interaction Validation (via mocks)
- Azure SDK classes mocked in tests: `CosmosClient`, `ServiceBusClient`, `DefaultAzureCredential`
- Results: FAIL
  - Tests do attempt mocking, but the suite cannot import the production module because the Azure Service Bus dependency is missing at import time.
  - This prevents validating client construction and mock assertions in CI.
- Network calls detected in tests (should be ZERO): none detected; failure occurred before execution

## Layer 3: Contract Validation
- Schema match: NO
- Differences:
  - No sprint contract entries were discoverable in the migrated module for execution
  - Contract validation could not be performed because the module import failed before any handler invocation
- Contract checks passed: 0/Y

## Specific Issues Found
1. **Import error**: `azure.servicebus` is not installed or not available in the test environment.
2. **Blocking module import**: `function_app.py` imports Azure SDK symbols at import time, causing all tests to fail during collection.
3. **Contract not executable**: No contract check definitions were found in the migrated module, so Layer 3 could not be validated.

## Overall Verdict: FAIL
## Self-Healing Attempts: 1/3
## Coverage: 0% (baseline not verified)