# Test Harness — Verification Suite for Migration Frameworks

Three layers of testing to verify both `codex-harness` and `ms-agent-harness` work correctly.

## Layer 1: Unit Tests (no LLM needed, free)

Test individual components — tools, context engineering, persistence, config.

```bash
# codex-harness
cd codex-harness && pip install pytest pytest-cov httpx && pytest tests/ -v

# ms-agent-harness
cd ms-agent-harness && pip install pytest pytest-cov pytest-asyncio && pytest tests/ -v
```

## Layer 2: Integration Tests (mocked LLM, free)

Test the pipeline orchestration with mocked agent responses.

```bash
cd ms-agent-harness && pytest tests/test_integration.py -v
```

Verifies:
- Correct agent sequence (analyzer → coder → tester → reviewer)
- Self-healing loop (fail → retry → blocked after 3)
- Sprint contract negotiation
- Coverage ratcheting
- State updates (progress log, learned rules)
- Analysis caching (skip re-analysis on retry)

## Layer 3: E2E Smoke Test (real LLM, ~$1-5 per run)

Run both frameworks against the sample Python Lambda and verify outputs.

```bash
# Set credentials
export OPENAI_API_KEY=sk-...
# Or: export FOUNDRY_PROJECT_ENDPOINT=https://...

# Run both
python3 test-harness/smoke_test.py --both

# Or just one
python3 test-harness/smoke_test.py --codex-only
python3 test-harness/smoke_test.py --ms-only
```

Verifies:
- analysis.md exists and has content
- Azure Function code generated with no AWS imports
- sprint-contract.json is valid JSON
- review.md has a verdict (APPROVE/CHANGES_REQUESTED/BLOCKED)
- test-results.md exists

## Comparison Harness

After running the smoke test on both, compare their outputs:

```bash
python3 test-harness/compare.py --module order-processor
```

Scores both frameworks on 5 dimensions (18 points total):
1. **Analysis completeness** — dependencies, complexity, business logic (3 pts)
2. **Sprint contract** — unit checks, API checks, architecture checks (3 pts)
3. **Test results** — 3-layer evaluation + verdict (4 pts)
4. **Review quality** — checklist, confidence score, verdict (3 pts)
5. **Azure Function code** — handler, tests, deps, host.json, AWS-clean (5 pts)

## Full Test Run

```bash
# 1. Unit tests (both harnesses)
cd codex-harness && pytest tests/ -v && cd ..
cd ms-agent-harness && pytest tests/ -v && cd ..

# 2. Integration tests
cd ms-agent-harness && pytest tests/test_integration.py -v && cd ..

# 3. E2E + comparison (requires LLM credentials)
python3 test-harness/smoke_test.py --both
python3 test-harness/compare.py
```
