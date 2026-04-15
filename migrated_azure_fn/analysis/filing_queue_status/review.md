# Code Review: filing_queue_status

## Sprint Contract Compliance
- Contract exists: YES
- Checks passed: 6/9
- Unaddressed checks: 
  - handler contract for retryable vs non-retryable failures is not correctly implemented
  - production import/package mismatch for `azure.servicebus`
  - offline importability is broken in the current environment because the module imports a package that is not available to the test harness

## Checklist Results
| # | Check | Status | Notes |
|---|-------|--------|-------|
| 1 | Business Logic | FAIL | `_process()` correctly handles malformed JSON, missing fields, Delaware COGS bypass, and busy-state retry signaling, but `handler()` collapses all non-`ok` results into `batchItemFailures`. The sprint contract explicitly says malformed JSON and validation errors must not be retryable. That semantic split is missing. |
| 2 | No AWS Artifacts | PASS | No AWS SDK imports or AWS strings were found in the migrated module. |
| 2.5 | Self-Contained Module | PASS | No sibling-package imports were found. |
| 2.6 | No Module-Scope I/O or SDK Construction | PASS | The Azure clients are created through cached factory functions, not at import time. Top-level code is import-safe in principle. |
| 3 | Azure Best Practices | FAIL | The module imports `azure.servicebus.ServiceBusMessage`, but the evaluation reported `ModuleNotFoundError: No module named 'azure.servicebus'` during collection. Also, the trigger/handler shape is duplicated in a way that does not clearly preserve the original queue contract. |
| 4 | Error Handling | FAIL | Busy-state retry behavior is present, but there is no distinct non-retryable path in `handler()`. Malformed/validation failures are incorrectly treated as retryable by the batch failure logic. |
| 5 | Configuration | PASS | Required settings are mapped in `local.settings.json` and Bicep app settings. |
| 6 | Security | PASS | No hardcoded secrets were found in the code. Key Vault reference is used for the Service Bus connection. |
| 7 | Performance | PASS | Client construction is cached with `lru_cache`, which is appropriate. |
| 8 | Infrastructure | PASS | Bicep exists and is broadly aligned with the module; any template issues are non-blocking in this phase. |

## Confidence Score: 62/100

## Issues Found
### Blocking
- [filing_queue_status/function_app.py:12-13] Importing `azure.servicebus.ServiceBusMessage` caused test collection failure in the offline harness (`ModuleNotFoundError: No module named 'azure.servicebus'`). This is a hard stop because the module cannot be imported in the current validation environment.
- [filing_queue_status/function_app.py:122] `handler()` marks every non-`ok` result as a retryable batch failure. This contradicts the contract requirement that malformed JSON and validation failures must be non-retryable.

### Non-Blocking
- [filing_queue_status/function_app.py:24-48] `_error_payload()` exists but is not used in the main processing path, so standardized structured error responses are not consistently enforced.
- [filing_queue_status/function_app.py:55-75] The code relies on environment variables for Azure client construction, which is acceptable via factories, but the module’s dependency surface still needs to match the installed Azure SDK packages exactly.

## Learned Rules Applied
No learned rules were available in `learned-rules.md` for this review.

## Bicep validation skipped
- The Bicep template is present conceptually in the supplied migration payload, but no workspace file could be validated with the jailed tools in this session.

## Recommendation: BLOCKED
## Summary: The migration is close, but it is not shippable yet. The module fails offline import/collection due to an Azure SDK package mismatch, and the handler’s batch-failure semantics do not preserve the sprint contract’s non-retryable validation behavior.