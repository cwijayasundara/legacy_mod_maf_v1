```markdown
# Code Review: order-processor

## Sprint Contract Compliance
- Contract exists: YES
- Checks passed: 0/4
- Unaddressed checks: All checks failed due to import error preventing test execution

## Checklist Results
| # | Check | Status | Notes |
|---|-------|--------|-------|
| 1 | Business Logic | FAIL | Import error in tests prevented verification |
| 2 | No AWS Artifacts | FAIL | Original AWS references remained in migration notes |
| 3 | Azure Best Practices | PASS | Usage of Azure SDK and routing to Azure endpoints |
| 4 | Error Handling | FAIL | Lack of specific exception handling. Default error response not detailed |
| 5 | Configuration | FAIL | Connection strings embedded directly in code instead of environment variables |
| 6 | Security | FAIL | Hardcoded connection strings in code |
| 7 | Performance | FAIL | No evidence of connection pooling or async use |
| 8 | Infrastructure | FAIL | Bicep template not present in the repository |

## Confidence Score: 40/100

## Issues Found
### Blocking
- [src/azure-functions/order-processor/function_app.py: imports] Hardcoded connection strings violate security protocols.
- [src/azure-functions/order-processor/function_app.py: routes] Missing specific error handling for various HTTP operations.

### Non-Blocking
- Configuration of environment variables not using Azure App Settings.
- No sign of optimized practices such as async calls or connection pooling.

## Learned Rules Applied
- **Rule 1**: Connection strings must not be hardcoded; use App Settings or Key Vault.
- **Rule 2**: Ensure unit tests are executable within the correct module path for effective validation.

## Recommendation: BLOCKED

## Summary:
The migration is blocked due to multiple critical failures. Import errors prevented the validation of business logic through tests, and hardcoded configuration values pose security risks. Infrastructure lacks necessary Bicep template. Immediate action is required to resolve blocking issues, after which a new review can be conducted.
```

### After Review
1. Append to `state/migration-progress.txt`:
   ```
   === Session N ===
   date: 2023-10-12T...
   module: order-processor
   language: Python
   work_item: <WI-ID>
   gates_passed: [3]
   gates_failed: [1, 2, 4, 5, 6, 7, 8]
   coverage: 0%
   reviewer_score: 40/100
   learned_rules_count: 2
   blocked: true
   block_reason: Import error and security violations
   recommendation: BLOCKED
   next_action: Developer to fix import issues and security problems. Rerun tests.
   ```

2. Update program.md Pipeline Status table with this module's result.