### Evaluation of Migrated Azure Function for Module 'order-processor'

#### Layer 1: Unit Tests
- **Test File**: `tests/test_order_processor.py`
- **Tests and What They Verify**:
  1. **`test_create_order`**: Verifies that a valid order input leads to a success response with the correct order ID.
  2. **`test_get_order`**: Verifies that fetching an existing order returns the correct data and status.
  3. **`test_create_order_invalid_json`**: Validates that providing invalid JSON raises a `KeyError`.
  4. **`test_get_order_not_found`**: Verifies the response for a non-existent order ID returns an appropriate error message.

- **Test Results**: 
  - **Total Tests**: 4
  - **Pass/Fail**: All tests fail due to an import error.
  
- **Coverage**: 
  - **Coverage Percentage**: 0%, as no tests were successfully executed.

#### Issues Found:
- **Import Error**: The following error occurred while trying to run the unit tests:
  ```
  ModuleNotFoundError: No module named 'src.azure_functions'
  ```
  This indicates that the module structure may not be correctly referenced in the test files.

### Layer 2: Integration Tests
- **SDK Usage**: The code initializes Azure clients properly using `HttpRequest`, `HttpResponse`, and `FunctionContext`.
- **Emulators for Integration**: Not executed due to import issues in unit tests. Integration tests cannot proceed without resolving the unit test failures.

### Layer 3: Contract Validation
- **Sprint Contract Presence**: Contract is provided in `sprint-contract.json`.
- **API Contract Checks**: Not executed due to prior failures.

### Overall Verdict: **FAIL**
- The unit tests did not run successfully, resulting in a complete check failure. No integration or contract validation could be performed.

### Self-Healing Attempts: 1/3
- **Attempt 1**: Documented failure in JSON format as required:

```json
{
  "module": "order-processor",
  "attempt": 1,
  "timestamp": "2023-10-12T...",
  "overall_verdict": "FAIL",
  "failures": [
    {
      "failure_id": "F001",
      "layer": "unit",
      "error_category": "import_error",
      "description": "Module not found during test execution.",
      "file": "src/azure-functions/order-processor/tests/test_order_processor.py",
      "line": 3,
      "stack_trace": "Traceback [full error traced omitted for brevity]",
      "expected": "Valid module path.",
      "actual": "Module 'src.azure_functions' not found.",
      "self_healing_strategy": "Check module path and update the import statement."
    }
  ],
  "prior_attempts": []
}
```

### Test Results Documentation
```markdown
# Test Results: order-processor

## Layer 1: Unit Tests
- Total: 4 | Passed: 0 | Failed: 4
- Coverage: 0%
- Ratchet: FAIL
- Failures: [F001: Module not found during test execution]

## Layer 2: Integration Tests
- Emulators used: None (tests not executed)
- Results: Not executed due to unit test failure

## Layer 3: Contract Validation
- Schema match: Not executed
- Contract checks passed: Not executed

## Overall Verdict: FAIL
## Self-Healing Attempts: 1/3
```

### Next Steps
The developer should address the import error in the unit tests to allow for successful execution. After correcting the issue, the evaluation process can be re-initiated.