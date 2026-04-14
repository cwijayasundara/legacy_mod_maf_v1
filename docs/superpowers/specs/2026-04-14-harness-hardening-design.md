# Harness Hardening (Sub-project D.2) — Design Spec

**Date:** 2026-04-14
**Status:** Draft — pending review
**Target repo:** `ms-agent-harness`
**Depends on:** all prior sub-projects (A, B, C, D.1) merged.

---

## 1. Context

The pipeline now has substantial surface area: discovery (5 LLM stages),
migration (5 LLM stages × N modules), fanout, evaluation, and AGENTS.md-aware
agents. Three operator concerns are still unmet:

1. **Runaway costs.** A stuck self-heal loop, a network stall, or a bad prompt
   can chew through tokens indefinitely. Today there is no hard stop.
2. **Un-correlatable logs.** Log lines from concurrent `/migrate-repo` waves
   interleave without any way to group them by run or by module. `repo_id`
   appears in some messages but not all.
3. **No wallclock budget.** A single `agent.run()` can block forever if the
   Azure/OpenAI endpoint stalls. The only existing safety valve is the
   3-attempt retry on rate-limit and context-length — both of which return
   promptly.

This spec introduces three additive capabilities to close those gaps:

1. **Timeouts at two layers** — per-LLM-call and per-stage.
2. **Structured logging with trace IDs** — `ContextVar`-backed filter, JSON
   output via `LOG_FORMAT=json`.
3. **Token budget** — per-run cap; runs abort when crossed.

Cancellation (`/cancel` endpoint), per-module cost reporting, USD billing,
retry classification, and OpenTelemetry emission are out of scope.

## 2. Scope

### In scope

- New `agent_harness/observability.py` — ContextVars, logging filter, token
  counter, helpers.
- `base.run_with_retry` extended with `asyncio.wait_for(..., timeout=settings.timeouts.per_call_seconds)`
  and token accounting on success.
- Per-stage timeouts wrap every migration stage (analyzer, coder, tester,
  reviewer, security) inside `MigrationPipeline.run`, and the discovery
  `run_stage` gains an optional `stage_timeout` arg.
- `config/settings.yaml` extended with `timeouts:` and `cost:` blocks plus a
  `Settings.timeout_for(role)` helper.
- Entry-point integration in `orchestrator/api.py`: every public endpoint
  generates a trace, starts a token counter, maps `TokenBudgetExceeded` to
  HTTP 402.
- `lifespan` installs logging once via `observability.init_logging`.
- Unit tests for every component + an integration test exercising each
  failure mode (token cap, call timeout, stage timeout).

### Out of scope (future)

- Cancellation via `/cancel/{run_id}`. Needs cooperative task model; deferred.
- USD billing (price table). Operators can translate tokens→USD externally.
- Per-module cost in `migrate_repo_module_runs.review_score` column.
- Retry classification beyond existing rate-limit / context-length / timeout.
- OpenTelemetry spans / Azure Monitor integration.
- Timeout overrides per-repo via AGENTS.md (conflates config surfaces).
- Resuming a run that aborted on cap; operator re-runs with a bigger cap.

## 3. Architecture

### 3.1 Placement

```
ms-agent-harness/
└── agent_harness/
    ├── observability.py        [NEW] ContextVars, filter, TokenCounter, helpers
    ├── base.py                 [modify] run_with_retry: per-call timeout + usage accounting
    ├── config.py               [modify] load timeouts + cost blocks; timeout_for()
    ├── pipeline.py             [modify] per-stage timeout wrappers; set_stage context
    ├── discovery/workflow.py   [modify] run_stage gets optional stage_timeout
    └── orchestrator/api.py     [modify] trace + token-counter init on every endpoint;
                                         lifespan installs logging; 402 mapping

config/settings.yaml             [modify] timeouts + cost blocks

tests/
├── test_observability.py       [NEW]
├── test_run_with_retry_timeout.py  [NEW]
├── test_run_with_retry_usage.py    [NEW]
├── test_pipeline_stage_timeout.py  [NEW]
├── test_discovery_stage_timeout.py [NEW]
├── test_token_budget_api.py    [NEW]
└── test_logging_json.py        [NEW]
```

### 3.2 Reuse of existing infrastructure

- Existing `run_with_retry` wrapper already centralises every `agent.run()`
  invocation. Extending it touches one function and every caller benefits.
- `logger = logging.getLogger("...")` calls are already pervasive. A single
  `logging.Filter` attached to the root handler makes every existing call
  site emit structured context without code edits.
- `config.Settings` already loads `rate_limits`, `chunking`, `quality` from
  YAML. Adding two more dataclasses follows the same pattern.
- `run_stage` in `discovery/workflow.py` already catches exceptions during
  produce/critic; adding a timeout wrapper is additive.

## 4. Components

### 4.1 `agent_harness/observability.py` — NEW

```python
"""Run-level observability: trace IDs, structured logging, token budget."""
from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4


TRACE_ID: ContextVar[str] = ContextVar("trace_id", default="")
STAGE: ContextVar[str] = ContextVar("stage", default="")
ATTEMPT: ContextVar[int] = ContextVar("attempt", default=0)


@dataclass
class TokenCounter:
    input_tokens: int = 0
    output_tokens: int = 0
    cap_tokens: int | None = None

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


TOKEN_COUNTER: ContextVar[TokenCounter | None] = ContextVar("token_counter", default=None)


class TokenBudgetExceeded(RuntimeError):
    """Raised when cumulative token usage crosses the configured cap."""


def new_trace(prefix: str) -> str:
    tid = f"{prefix}-{uuid4().hex[:8]}"
    TRACE_ID.set(tid)
    return tid


def set_stage(name: str, attempt: int = 0) -> None:
    STAGE.set(name)
    ATTEMPT.set(attempt)


def start_run(cap_tokens: int | None) -> TokenCounter:
    counter = TokenCounter(cap_tokens=cap_tokens)
    TOKEN_COUNTER.set(counter)
    return counter


def charge(input_tokens: int, output_tokens: int) -> None:
    c = TOKEN_COUNTER.get()
    if c is None:
        return
    c.input_tokens += input_tokens
    c.output_tokens += output_tokens
    if c.cap_tokens is not None and c.total > c.cap_tokens:
        raise TokenBudgetExceeded(
            f"token cap {c.cap_tokens} exceeded "
            f"(in={c.input_tokens}, out={c.output_tokens}, total={c.total})"
        )


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = TRACE_ID.get()
        record.stage = STAGE.get()
        record.attempt = ATTEMPT.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", ""),
            "stage": getattr(record, "stage", ""),
            "attempt": getattr(record, "attempt", 0),
            "message": record.getMessage(),
        })


def init_logging(fmt: Literal["text", "json"] = "text") -> None:
    """Install the ContextFilter on the root logger and pick a formatter.

    Idempotent: subsequent calls replace the handler.
    """
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ContextFilter())
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s "
            "[trace=%(trace_id)s stage=%(stage)s attempt=%(attempt)s] "
            "%(message)s"
        ))
    root.addHandler(handler)
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
```

### 4.2 `config.py` — new settings blocks

```python
@dataclass
class TimeoutConfig:
    per_call_seconds: int = 120
    per_stage_seconds: dict[str, int] = field(default_factory=lambda: {
        "analyzer": 600, "coder": 900, "tester": 600,
        "reviewer": 300, "security": 300,
        "scanner": 300, "grapher": 600, "brd": 900,
        "architect": 900, "stories": 600,
    })


@dataclass
class CostConfig:
    per_run_token_cap: int | None = None
```

`Settings` gains:

```python
timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
cost: CostConfig = field(default_factory=CostConfig)

def timeout_for(self, role: str) -> int:
    return self.timeouts.per_stage_seconds.get(role, 600)
```

`load_settings()` reads `raw.get("timeouts", {})` / `raw.get("cost", {})` and
constructs the dataclasses. Back-compat preserved: a YAML missing both blocks
yields defaults.

### 4.3 `base.run_with_retry` — per-call timeout + usage accounting

Current body:

```python
async def run_with_retry(agent, message: str, max_retries: int = 3) -> str:
    for attempt in range(max_retries):
        try:
            result = await agent.run(message)
            return result.text
        except Exception as e:
            ...
```

Extended body (pseudo-code; actual implementation preserves existing
exponential backoff and context-length paths):

```python
async def run_with_retry(agent, message: str, max_retries: int = 3) -> str:
    from . import observability
    timeout = get_settings().timeouts.per_call_seconds
    for attempt in range(max_retries):
        try:
            result = await asyncio.wait_for(agent.run(message), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("agent.run timeout after %ds (attempt %d/%d)",
                            timeout, attempt + 1, max_retries)
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
            continue
        except Exception as e:
            # existing rate-limit / context-length handling unchanged
            ...

        # Charge token budget using whatever usage info we can get.
        input_tokens, output_tokens = _extract_usage(result, message)
        observability.charge(input_tokens, output_tokens)  # may raise TokenBudgetExceeded
        return result.text

    raise RuntimeError(f"Agent failed after {max_retries} retries")


def _extract_usage(result, message: str) -> tuple[int, int]:
    """Pull usage from the agent result if available; else approximate."""
    usage = getattr(result, "usage", None)
    if usage is not None:
        in_t = int(getattr(usage, "input_tokens", 0) or 0)
        out_t = int(getattr(usage, "output_tokens", 0) or 0)
        if in_t or out_t:
            return in_t, out_t
    # Fallback: char/4 heuristic (no tiktoken dependency for v1).
    return len(message) // 4, len(getattr(result, "text", "")) // 4
```

Design notes:
- The char/4 approximation avoids a new `tiktoken` dependency. It's off by
  ~20–30% on typical text but conservative enough for a budget cap (errs
  toward firing the cap sooner).
- `TokenBudgetExceeded` propagates out of `run_with_retry` — NOT caught as
  retryable. Aborts the in-flight run immediately.

### 4.4 Per-stage timeouts

**Migration (`MigrationPipeline.run`):** wrap each agent-stage invocation
with `asyncio.wait_for` using `settings.timeout_for(role)`:

```python
try:
    analysis = await asyncio.wait_for(
        analyze_module(module=module, language=language, ...),
        timeout=self.settings.timeout_for("analyzer"),
    )
except asyncio.TimeoutError:
    self.repo.complete_run(run_id, "blocked", f"analyzer timed out after {settings.timeout_for('analyzer')}s")
    return PipelineResult(module=module, status="blocked",
                           message=f"analyzer timed out", ...)
```

Same pattern for `migrate_module`, `evaluate_module`, `review_module`,
`security_review`. Also `observability.set_stage(role, attempt=attempt)` is
called before each one so logs carry the stage label.

**Discovery (`workflow.run_stage`):** new optional `stage_timeout` parameter:

```python
async def run_stage(..., stage_timeout: int | None = None) -> str:
    ...
    for attempt in range(1, MAX_ATTEMPTS + 1):
        observability.set_stage(stage_name, attempt)
        try:
            if stage_timeout:
                result = await asyncio.wait_for(produce(feedback), timeout=stage_timeout)
            else:
                result = await produce(feedback)
        except asyncio.TimeoutError:
            report = CriticReport(verdict="FAIL",
                reasons=[f"stage timed out after {stage_timeout}s"],
                suggestions=["Re-run with a higher stage timeout or investigate the stall."])
            feedback = _feedback_from_report(report)
            last = report
            continue
        ...
```

`run_discovery` passes `stage_timeout=settings.timeout_for(stage_name)` for
each stage.

### 4.5 Orchestrator integration

Every FastAPI handler in `orchestrator/api.py` starts with:

```python
from agent_harness import observability

@app.post("/discover", ...)
async def discover(req: DiscoverRequest):
    settings = load_settings()
    trace_id = observability.new_trace("discover")
    observability.start_run(settings.cost.per_run_token_cap)
    logger.info("discover started repo_id=%s trace=%s", req.repo_id, trace_id)
    try:
        result = await discovery_workflow.run_discovery(
            repo_id=req.repo_id, repo_path=req.repo_path, repo=_discovery_repo,
        )
    except observability.TokenBudgetExceeded as exc:
        raise HTTPException(402, str(exc))
    ...
```

Same pattern on `/plan`, `/approve`, `/migrate`, `/migrate/sync`,
`/migrate-repo`, `/migrate-repo/sync`. The trace prefix encodes the endpoint
(e.g. `migrate-repo-ab12cd34`).

`lifespan` calls `observability.init_logging(os.environ.get("LOG_FORMAT", "text"))`
once, just after the existing `logging.basicConfig(...)` line (which can be
removed — `init_logging` replaces it).

### 4.6 Settings YAML — `config/settings.yaml`

Appended blocks:

```yaml
timeouts:
  per_call_seconds: 120
  per_stage_seconds:
    analyzer: 600
    coder: 900
    tester: 600
    reviewer: 300
    security: 300
    scanner: 300
    grapher: 600
    brd: 900
    architect: 900
    stories: 600

cost:
  per_run_token_cap: null   # integer to enable; null disables
```

## 5. Data contracts

### 5.1 JSON log line (when `LOG_FORMAT=json`)

```json
{
  "ts": "2026-04-14T14:00:00Z",
  "level": "INFO",
  "logger": "pipeline",
  "trace_id": "migrate-ab12cd34",
  "stage": "analyzer",
  "attempt": 1,
  "message": "[Gate 1] Running analyzer for orders"
}
```

When `LOG_FORMAT=text` (default), the text formatter inlines the same fields:

```
2026-04-14 14:00:00 INFO pipeline [trace=migrate-ab12cd34 stage=analyzer attempt=1] [Gate 1] Running analyzer for orders
```

### 5.2 `TokenBudgetExceeded` HTTP response

Status: **402 Payment Required**. Body:

```json
{"detail": "token cap 500000 exceeded (in=412000, out=91000, total=503000)"}
```

### 5.3 `Settings.timeouts.per_stage_seconds` default map

Per-role seconds: analyzer 600, coder 900, tester 600, reviewer 300,
security 300, scanner 300, grapher 600, brd 900, architect 900, stories 600.
Per-call default: 120s. Roles not in the map use 600s (`timeout_for`'s
fallback).

## 6. Control flow

### 6.1 Happy path — `/discover`

```
POST /discover
 → trace_id = new_trace("discover")
 → counter  = start_run(cap_tokens=settings.cost.per_run_token_cap)
 → run_discovery(repo_id, repo_path, repo):
     for each stage in [scanner, grapher, brd, architect, stories]:
        set_stage(stage, attempt=1)
        run_stage(..., stage_timeout=settings.timeout_for(stage))
        └─ produce(feedback) inside asyncio.wait_for(stage_timeout)
           └─ _run_agent(msg) → run_with_retry(agent, msg):
              └─ asyncio.wait_for(agent.run(msg), timeout=120s)
              └─ charge(input_tokens, output_tokens)  # may raise TokenBudgetExceeded
 → return 200 with artifact paths
```

### 6.2 Failure paths

**Per-call timeout:** `asyncio.TimeoutError` → `run_with_retry` retries with
backoff → if all retries time out, exception bubbles up → stage's critic
loop records a FAIL reason and retries (discovery) / `MigrationPipeline`
records `blocked` (migration).

**Per-stage timeout:** `asyncio.TimeoutError` in the stage wrapper → discovery
treats it as critic FAIL, self-heals up to 3× → `blocked.md`. Migration
short-circuits the rest of the pipeline with `status="blocked"`.

**Token cap exceeded:** `TokenBudgetExceeded` from `charge()` →
unhandled through every retry layer → API maps to HTTP 402 → partial
artifacts on disk are preserved for inspection.

## 7. Error handling

| Condition | Behaviour |
|---|---|
| Per-call timeout, attempt < max | Retry with exponential backoff (existing) |
| Per-call timeout, max reached | Surface; stage treats as critic FAIL |
| Per-stage timeout, attempt < max | Treated as critic FAIL; next self-heal attempt |
| Per-stage timeout, max reached | Discovery: `blocked.md`. Migration: `PipelineResult(status="blocked")`. |
| Token cap exceeded | `TokenBudgetExceeded` → 402. No retry. |
| `agent.run` returns no `usage` | Fallback to char/4 heuristic for both directions. |
| Logging not initialised (edge case during test imports) | `ContextFilter` defaults each field to empty string / 0; records still emit. |
| `LOG_FORMAT` unset or invalid | Default to `"text"`. |

## 8. Testing

Unit (no LLM):

- `tests/test_observability.py`
  - `new_trace("x")` returns `x-<hex>` and `TRACE_ID.get()` returns same.
  - `set_stage("analyzer", 2)`; `STAGE.get()=="analyzer"`, `ATTEMPT.get()==2`.
  - `TokenCounter.total` correctly sums.
  - `start_run(cap_tokens=None)` → `charge(a, b)` never raises.
  - `start_run(cap_tokens=100)` → `charge(60, 50)` raises
    `TokenBudgetExceeded`.
  - `ContextFilter.filter(record)` attaches `trace_id`, `stage`, `attempt`.
  - `init_logging("json")` installs one handler whose formatter is
    `_JsonFormatter`; `init_logging("text")` installs one whose formatter is
    a `logging.Formatter`.
- `tests/test_run_with_retry_timeout.py`
  - Monkeypatch `settings.timeouts.per_call_seconds = 1`. Agent sleeps 2s →
    first call `TimeoutError`, second call returns promptly, result text
    returned.
  - Agent always sleeps 2s → final `RuntimeError("Agent failed after 3
    retries")`.
- `tests/test_run_with_retry_usage.py`
  - Agent returns result with `usage.input_tokens=100, output_tokens=50` →
    `TOKEN_COUNTER.get()` reflects +100/+50.
  - Agent returns result with no `usage` → fallback to char/4 heuristic.
  - Cap 100; agent returns 1000 input-token response → raises.
- `tests/test_pipeline_stage_timeout.py`
  - Mock `analyze_module` to sleep past the analyzer timeout (1s in this
    test); pipeline returns `PipelineResult(status="blocked", message~"timed
    out")`.
- `tests/test_discovery_stage_timeout.py`
  - Mock scanner `_run_agent` to sleep past its timeout; `run_discovery`
    either self-heals (subsequent fast responses) or ends with
    `RuntimeError("stage scanner blocked...")`.
- `tests/test_token_budget_api.py`
  - `TestClient.post("/discover", ...)` with settings mocking
    `per_run_token_cap=1` and a mocked `_run_agent` that always charges more
    → response status code 402.
- `tests/test_logging_json.py`
  - `init_logging("json")`; emit a `logger.info(...)` inside a `new_trace` /
    `set_stage` context; capture stdout; assert each line is valid JSON
    containing `trace_id` / `stage` / `attempt` / `message`.

Smoke: `LOG_FORMAT=json python -m agent_harness.eval run --corpus=synthetic
--tier=deterministic` produces JSON lines; grep for non-empty `trace_id`
field.

## 9. Migration plan (how this ships)

1. `observability.py` + unit tests for ContextVars, TokenCounter, Filter,
   init_logging.
2. `config.py` + `settings.yaml` — load `timeouts` and `cost` blocks.
3. `base.run_with_retry` — per-call timeout + token accounting.
4. `MigrationPipeline.run` — per-stage timeout wrappers + `set_stage` calls.
5. `discovery.workflow.run_stage` — optional `stage_timeout`.
6. `orchestrator/api.py` — trace + start_run on every endpoint; 402 mapping;
   lifespan installs logging.
7. Integration tests across the three failure modes.
8. Smoke test for JSON log format.
9. README section documenting operator knobs.

Each step is independently testable; order minimises blocking.

## 10. Open questions (none blocking)

- The char/4 token heuristic is rough. If accounting needs to be precise,
  adding `tiktoken` later is a ~10-line change. v1 accepts the
  approximation.
- `LOG_LEVEL` env var handling currently sits on the root logger; the
  existing `logging.basicConfig(level=logging.INFO, ...)` call in the
  orchestrator conflicts. `init_logging` removes old handlers to keep
  behaviour predictable.
- The per-call timeout of 120s is conservative; LLMs often respond in
  10–30s. Operators can tune in settings without code changes.

---

**Next step:** user reviews, then implementation plan via `writing-plans`.
