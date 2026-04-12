## Quality Principles — Mandatory for ALL Code You Write

You MUST follow these quality principles in all code you write. Violations will be caught by automated quality gates and will block your output.

### Principle 1: Small Modules
- **Max 300 lines per file** (BLOCK if exceeded)
- Warning at 200 lines — consider splitting
- One module = one responsibility
- If a file is growing, extract helpers into a sub-module

### Principle 2: Static Typing
- **Every function must have return type annotations** (Python: `-> type`, TypeScript: `: ReturnType`)
- Every function parameter must be typed
- Use `@dataclass` or Pydantic models for structured data — never raw dicts for domain objects
- Exceptions: `__init__`, `__str__`, `__repr__` do not require return annotations

### Principle 3: Functions Under 50 Lines
- **Max 100 lines per function** (BLOCK if exceeded)
- Warning at 50 lines — refactor into smaller helpers
- Each function should do ONE thing
- Extract complex conditionals into named helper functions

### Principle 4: Single Owner for State Mutations
- Only ONE module should write to any given database table or state store
- Other modules read via that owner's API/service
- If you need to write to a table, check if an existing repository module owns it
- Never duplicate DB write logic across services

### Principle 5: Explicit Error Handling
- **NEVER use bare `except:`** (BLOCK)
- **Avoid `except Exception:`** — catch specific exception types (WARN)
- Always log the exception with context (module, operation, relevant IDs)
- Return structured error responses with appropriate HTTP status codes:
  ```python
  # Good
  except CosmosResourceNotFoundError as e:
      logger.warning("Item %s not found in %s: %s", item_id, container, e)
      return func.HttpResponse(json.dumps({"error": "Not found"}), status_code=404)
  
  # Bad
  except:
      return func.HttpResponse("Error", status_code=500)
  ```

### Principle 6: No Dead Code
- Remove all commented-out code before submitting
- Remove unused imports
- Remove unused variables and functions
- If code is "saved for later," put it in a separate branch — not in comments

---

## Testing Standards

- **Minimum 80% code coverage** (enforced by ratchet — coverage can only go UP)
- Every public function must have at least one test
- Test structure: Arrange / Act / Assert with clear section comments
- Test names describe the scenario: `test_create_order_returns_400_when_missing_required_fields`
- Mock external services (Azure SDK, HTTP clients) — never call real services in unit tests
- Integration tests go in a separate `tests/integration/` directory

## Logging Standards

- Use structured logging with consistent fields: `module`, `operation`, `duration_ms`, `status`
- Log at appropriate levels:
  - `DEBUG`: Detailed diagnostic info (not in production)
  - `INFO`: Normal operations (startup, request received, operation completed)
  - `WARNING`: Recoverable issues (retry, fallback, degraded)
  - `ERROR`: Failures requiring attention (unhandled exception, external service down)
- Include correlation IDs in all log entries for distributed tracing
- Never log secrets, tokens, passwords, or PII

## Error Response Format

All HTTP-triggered functions must return errors in this format:
```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Order with ID 12345 not found",
    "details": []
  }
}
```
- Use appropriate HTTP status codes (400, 401, 403, 404, 409, 422, 500)
- Never expose internal stack traces to callers
- Include a machine-readable error code for client-side handling
