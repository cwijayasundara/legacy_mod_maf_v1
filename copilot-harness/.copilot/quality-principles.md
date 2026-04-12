# Code Quality Principles

These principles apply to ALL code written by agents. Non-negotiable.

## 1. Small Modules
- Max 300 lines per file (BLOCK), warn at 200
- One responsibility per file
- Split when approaching limit

## 2. Static Typing
- Python: full type hints on all functions (params + return)
- Node.js: JSDoc types or TypeScript
- Zero `any` types allowed
- Type aliases for domain concepts (OrderId = str, not just str)

## 3. Functions Under 50 Lines
- Warn at 50, BLOCK at 100
- Decompose into named sub-functions
- Each function testable in isolation

## 4. Single Owner for State Mutations
- Every DB write, file write, queue publish has ONE call site
- No duplicate record creation across files
- Repository pattern: one class owns each entity's persistence

## 5. Explicit Error Handling
- Typed error classes per domain (OrderNotFoundError, not generic Exception)
- Never bare except/catch
- All error paths tested
- Structured error responses: {"error_code": "...", "message": "...", "details": {}}

## 6. No Dead Code
- Every line traces to a requirement
- No commented-out code
- No unused imports
- No speculative features ("we might need this later")

## Testing Rules (TDD Mandatory)
- Write failing test FIRST -> implement -> verify pass
- 100% meaningful coverage target, 80% floor
- Only mock external boundaries (DB, APIs, file I/O)
- Never mock business logic
- Realistic test data (no "foo", "test", 123)
- Test names describe behavior: "returns_404_when_order_not_found"

## Structured Logging
- INFO for business events, WARNING for recoverable issues, ERROR for failures
- Include context: {"order_id": "...", "processing_time_ms": 42}
- Never log secrets, tokens, PII
- Request ID tracing across all log entries

## Error Response Format
All API error responses MUST follow:
{"error_code": "UPPER_SNAKE_CASE", "message": "Human readable", "details": {}}
Status mapping: 400=validation, 404=not found, 409=conflict, 422=processing, 500=internal
