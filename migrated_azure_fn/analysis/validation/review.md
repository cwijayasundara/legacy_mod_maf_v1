# Code Review: validation

## Sprint Contract Compliance
- Contract exists: YES
- Checks passed: 0/11
- Unaddressed checks: all unit_checks, all integration_checks, all contract_checks

## Checklist Results
| # | Check | Status | Notes |
|---|-------|--------|-------|
| 1 | Business Logic | FAIL | The migrated handler is not behaviorally aligned with the sprint contract: missing `ddbId` returns HTTP 200 soft-failure as expected, but the imported test harness already shows import-time failures preventing any contract execution. Also, the production code still uses `record["serviceType"]` without fallback, so legacy data can raise `KeyError` before publishing. |
| 2 | No AWS Artifacts | PASS | No AWS SDK imports or `amazonaws` references found in `validation/`. |
| 3 | Azure Best Practices | FAIL | `function_app.py` constructs Azure SDK clients through importable factories, which is good, but the module is not actually import-safe in the test environment because the Azure Service Bus package is missing at collection time. The module also keeps a synchronous style for SDK calls, which is acceptable here, but the failing import blocks the quality gate. |
| 4 | Error Handling | FAIL | The handler uses a broad `except Exception` and converts unexpected failures into a response, which is weaker than specific exception handling. Contracted retry/poison-message semantics are also not evidenced in the code. |
| 5 | Configuration | PASS | Required settings are mapped to app settings in `local.settings.json` and Bicep. |
| 6 | Security | PASS | No hardcoded secrets or AWS credentials remain in the visible production code. |
| 7 | Performance | PASS | Client construction is cached with `@lru_cache`; no module-scope network calls were found. |
| 8 | Infrastructure | PASS | Bicep is present and structurally reasonable, but validation could not be completed because the path was not found by the tool. This remains non-blocking. |

## Confidence Score: 61/100

## Issues Found
### Blocking
- [validation/function_app.py:13-14] Direct import of `azure.servicebus` makes the production module fail to import when the dependency is absent in the local test harness, which caused the entire test collection to fail. This is a blocking migration defect because the module cannot be exercised by CI.
- [validation/function_app.py:97-116] The handler does not satisfy the sprint contract end-to-end because contract validation could not execute due to the import failure above; as a result, every unit and integration contract check remains unverified.

### Non-Blocking
- [validation/function_app.py:115] `record["serviceType"]` can raise `KeyError` for inconsistent legacy records. This is an uncovered edge case from the original Lambda analysis.
- [validation/function_app.py:103-116] Broad `except Exception` reduces retry visibility and hides specific transient failures.
- [validation/tests/test_validation.py:1-108] The tests mock Azure SDKs correctly in principle, but they do not prove the module is importable in the test environment; the suite is currently blocked by missing `azure.servicebus`.
- [infrastructure/validation/main.bicep] Bicep file was present in the prompt, but the validator tool could not locate it from the workspace root. Treat this as an informational infrastructure issue only.

## Learned Rules Applied
No repository-specific learned rules could be confirmed from the available `learned-rules.md`/`state/learned-rules.md` content in this review context.

## Recommendation: BLOCKED
## Summary: The migration is not ready because the production module cannot be imported in CI due to the Azure Service Bus dependency failure, which prevents all tests and contract checks from running.