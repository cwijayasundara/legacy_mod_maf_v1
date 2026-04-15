 # Code Review: data_generator

## Sprint Contract Compliance
- Contract exists: YES
- Checks passed: 2/16
- Unaddressed checks: [
  "handler(event, context) returns missing ddbId payload for absent/empty/whitespace ddbId",
  "handler(event, context) reads record by ddbId and returns success payload",
  "handler(event, context) propagates runtime failures into failure payload",
  "handler(event, context) deterministically fails when record is missing",
  "transformer path preserves load/transform/persist/update order",
  "error path invokes shared error handling side effects",
  "handler accepts extra fields with detail.ddbId present",
  "DynamoDB read integration check",
  "DynamoDB update integration check",
  "downstream publish integration check",
  "error side effects integration check",
  "contract checks 0/4 passed",
  "coverage baseline/coverage floor could not be verified from accessible state files"
]

## Checklist Results
| # | Check | Status | Notes |
|---|-------|--------|-------|
| 1 | Business Logic | FAIL | Core contract is only partially exercised. Tests exist for success/missing-id/runtime-failure/whitespace/error-side-effect, but import-time failure prevents validation and the implementation diverges from the stated legacy output in the source path handling and persistence semantics. |
| 2 | No AWS Artifacts | PASS | No AWS imports or `amazonaws` strings found in `data_generator/**`. |
| 3 | Azure Best Practices | FAIL | `function_app.py` imports Azure clients at module scope (`azure.cosmos`, `azure.identity`, `azure.servicebus`), which violates the lazy-construction requirement and makes import fragile. |
| 4 | Error Handling | FAIL | Broad exception aggregation is present in the handler. Also the module’s async send path relies on `asyncio.run` around a sync client call, and the test suite could not validate the configured retry/dead-letter semantics. |
| 5 | Configuration | FAIL | Config is sourced from environment variables, but the module-scope imports and the runtime test import failure indicate the app is not safely importable without Azure packages installed. |
| 6 | Security | PASS | No hardcoded secrets or AWS artifacts in production code. App settings are present in `local.settings.json`; no obvious secret leakage in the reviewed source. |
| 7 | Performance | FAIL | Module-scope SDK imports and `asyncio.run` in the request path are not ideal. The client factory pattern is present, but importability is blocked by missing Azure packages in the test environment. |
| 8 | Infrastructure | FAIL | Bicep exists, but validation could not be executed from the resolved workspace path; treat as informational only. There is also no evidence from the review that the function app plan resource exists in this Bicep snippet. |

## Confidence Score: 58/100

## Issues Found
### Blocking
- [data_generator/function_app.py:10-13] Azure SDK packages are imported at module scope. The contract requires the handler module to be importable with no env vars and no network access; the current implementation is also failing test collection because `azure.servicebus` is unavailable in the environment.
- [data_generator/function_app.py:39-43, 76-81] Client factory creation is not fully aligned with the required lazy/mockable pattern. The module still constructs Azure SDK types at import time through annotations/import dependencies, which prevents safe import in a bare test harness.

### Non-Blocking
- [data_generator/tests/test_data_generator.py:1-92] Tests cover the main happy path and a few failure cases, but the sprint contract’s integration checks are not fully demonstrated in the visible test file.
- [data_generator/function_app.py:87-100] Error handling uses a broad multi-exception catch; this is acceptable only if narrowed further in a later cleanup.
- [infrastructure/data_generator/main.bicep] Bicep validation could not be completed from the resolved workspace path in this review session; non-blocking informational note only.

## Learned Rules Applied
No module-specific learned rules were available or readable in the provided environment, so none were applied.

## Bicep validation errors
- `INVALID: file not found: infrastructure/data_generator/main.bicep`

## Recommendation: BLOCKED
## Summary: The module is not yet releasable because the Python entrypoint is not safely importable in the test harness and depends on Azure SDK imports at module scope. That is a blocking quality-gate failure regardless of the otherwise promising test coverage and contract intent.