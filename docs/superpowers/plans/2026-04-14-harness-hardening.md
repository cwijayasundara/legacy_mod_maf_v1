# Harness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add operator-safety to the harness: per-LLM-call and per-stage timeouts, ContextVar-backed structured logging with trace IDs and JSON output, and a per-run token budget cap that surfaces HTTP 402 when crossed.

**Architecture:** New `agent_harness/observability.py` owns all three concerns — ContextVars (`TRACE_ID`, `STAGE`, `ATTEMPT`, `TOKEN_COUNTER`), a logging Filter that attaches them to every record, a `TokenCounter` dataclass, and helpers (`new_trace`, `set_stage`, `start_run`, `charge`). `base.run_with_retry` wraps each `agent.run` in `asyncio.wait_for(per_call_timeout)`, charges the counter on success from `result.usage` or a char/4 fallback, and lets `TokenBudgetExceeded` propagate. Each stage in `MigrationPipeline.run` and `discovery.workflow.run_stage` wraps its produce step in `asyncio.wait_for(per_stage_timeout)`. FastAPI endpoints generate a trace, seed the counter, map `TokenBudgetExceeded` to 402, and the lifespan installs logging.

**Tech Stack:** Python 3.11 (`asyncio`, `contextvars`, `logging`, `json`, `uuid`), FastAPI, pytest + pytest-asyncio. Paths relative to `ms-agent-harness/`. Tests: `python3 -m pytest`. Pre-existing failures in `test_chunker`, `test_complexity_scorer`, `test_compressor`, `test_token_estimator`, `test_integration`, `test_ast_tools` are unrelated — regression checks stay scoped to files this plan touches.

---

## File Structure

| File | Responsibility |
|---|---|
| `agent_harness/observability.py` | **NEW** — ContextVars, TokenCounter, TokenBudgetExceeded, ContextFilter, JSON formatter, `new_trace`, `set_stage`, `start_run`, `charge`, `init_logging` |
| `agent_harness/config.py` | Add `TimeoutConfig`, `CostConfig`; load from YAML; `Settings.timeout_for(role)` helper |
| `config/settings.yaml` | Append `timeouts:` and `cost:` blocks |
| `agent_harness/base.py` | `run_with_retry` wraps each call in `asyncio.wait_for`; extracts usage or falls back; calls `observability.charge` |
| `agent_harness/pipeline.py` | Per-stage timeout wrappers around analyzer/coder/tester/reviewer/security; `observability.set_stage` before each |
| `agent_harness/discovery/workflow.py` | `run_stage` gains optional `stage_timeout`; `run_discovery` passes per-stage timeouts |
| `agent_harness/orchestrator/api.py` | Every endpoint calls `new_trace` + `start_run`; `TokenBudgetExceeded` → 402; `lifespan` calls `init_logging` |
| `tests/test_observability.py` | **NEW** — ContextVars, charge, cap, filter, init_logging |
| `tests/test_run_with_retry_timeout.py` | **NEW** |
| `tests/test_run_with_retry_usage.py` | **NEW** |
| `tests/test_pipeline_stage_timeout.py` | **NEW** |
| `tests/test_discovery_stage_timeout.py` | **NEW** |
| `tests/test_token_budget_api.py` | **NEW** |
| `tests/test_logging_json.py` | **NEW** |
| `README.md` | Append operator-knobs section |

**Conventions:**
- TDD per task: fail-first test, then implementation, commit.
- Tests mock `agent.run` at the call seam; no real LLM.
- Pre-existing `conftest.py` mock for `agent_framework` is unchanged.

---

## Task 1: `observability.py` — ContextVars, TokenCounter, Filter, init_logging

**Files:**
- Create: `agent_harness/observability.py`
- Test: `tests/test_observability.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_observability.py
import json
import logging
from io import StringIO

import pytest


def test_new_trace_sets_context_and_returns_id():
    from agent_harness.observability import new_trace, TRACE_ID
    tid = new_trace("discover")
    assert tid.startswith("discover-")
    assert len(tid.split("-", 1)[1]) == 8   # uuid hex slice
    assert TRACE_ID.get() == tid


def test_set_stage_updates_context():
    from agent_harness.observability import set_stage, STAGE, ATTEMPT
    set_stage("analyzer", 2)
    assert STAGE.get() == "analyzer"
    assert ATTEMPT.get() == 2


def test_token_counter_total_and_cap():
    from agent_harness.observability import TokenCounter, TokenBudgetExceeded
    c = TokenCounter(cap_tokens=100)
    assert c.total == 0
    c.input_tokens = 40
    c.output_tokens = 30
    assert c.total == 70
    # charge() is the canonical path — tested separately.


def test_charge_without_counter_is_noop():
    from agent_harness.observability import charge, TOKEN_COUNTER
    TOKEN_COUNTER.set(None)
    charge(1000, 1000)   # must not raise


def test_charge_under_cap_accumulates():
    from agent_harness.observability import start_run, charge
    c = start_run(cap_tokens=1000)
    charge(100, 50)
    charge(200, 100)
    assert c.input_tokens == 300
    assert c.output_tokens == 150
    assert c.total == 450


def test_charge_over_cap_raises_token_budget_exceeded():
    from agent_harness.observability import start_run, charge, TokenBudgetExceeded
    start_run(cap_tokens=100)
    with pytest.raises(TokenBudgetExceeded) as exc:
        charge(60, 50)
    assert "cap 100" in str(exc.value)
    assert "110" in str(exc.value)


def test_context_filter_attaches_fields():
    from agent_harness.observability import ContextFilter, new_trace, set_stage
    new_trace("x")
    set_stage("grapher", 3)
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname="", lineno=0,
        msg="hi", args=(), exc_info=None,
    )
    assert ContextFilter().filter(record) is True
    assert record.trace_id.startswith("x-")
    assert record.stage == "grapher"
    assert record.attempt == 3


def test_init_logging_json_emits_valid_json():
    from agent_harness import observability
    observability.init_logging("json")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    # Redirect handler stream to capture output.
    handler = root.handlers[0]
    buf = StringIO()
    handler.stream = buf
    observability.new_trace("t")
    observability.set_stage("scanner", 1)
    logging.getLogger("eval").info("hello world")
    line = buf.getvalue().strip()
    assert line
    data = json.loads(line)
    assert data["message"] == "hello world"
    assert data["trace_id"].startswith("t-")
    assert data["stage"] == "scanner"
    assert data["attempt"] == 1
    assert data["level"] == "INFO"


def test_init_logging_text_uses_text_formatter():
    from agent_harness import observability
    observability.init_logging("text")
    root = logging.getLogger()
    fmt = root.handlers[0].formatter
    assert fmt is not None
    # Plain logging.Formatter, not the _JsonFormatter.
    assert fmt.__class__.__name__ == "Formatter"


def test_init_logging_is_idempotent():
    from agent_harness import observability
    observability.init_logging("text")
    observability.init_logging("json")
    root = logging.getLogger()
    # Replaces rather than accumulates.
    assert len(root.handlers) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_observability.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `agent_harness/observability.py`**

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

    Idempotent: replaces any existing handlers on the root logger.
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

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_observability.py -v`
Expected: 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/observability.py tests/test_observability.py
git commit -m "feat(observability): ContextVars, TokenCounter, ContextFilter, init_logging"
```

---

## Task 2: Settings — `timeouts` + `cost` blocks

**Files:**
- Modify: `agent_harness/config.py`
- Modify: `config/settings.yaml`
- Test: `tests/test_settings_timeouts_cost.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings_timeouts_cost.py
import pytest
import yaml


def test_timeout_config_defaults():
    from agent_harness.config import TimeoutConfig
    t = TimeoutConfig()
    assert t.per_call_seconds == 120
    assert t.per_stage_seconds["analyzer"] == 600
    assert t.per_stage_seconds["coder"] == 900
    assert t.per_stage_seconds["scanner"] == 300


def test_cost_config_defaults():
    from agent_harness.config import CostConfig
    c = CostConfig()
    assert c.per_run_token_cap is None


def test_settings_timeout_for_known_role():
    from agent_harness.config import Settings, TimeoutConfig
    s = Settings(timeouts=TimeoutConfig(
        per_call_seconds=30,
        per_stage_seconds={"analyzer": 42, "coder": 55},
    ))
    assert s.timeout_for("analyzer") == 42
    assert s.timeout_for("coder") == 55


def test_settings_timeout_for_unknown_role_falls_back_to_600():
    from agent_harness.config import Settings
    assert Settings().timeout_for("novel-role") == 600


def test_load_settings_reads_yaml_blocks(tmp_path, monkeypatch):
    yaml_text = yaml.safe_dump({
        "timeouts": {
            "per_call_seconds": 45,
            "per_stage_seconds": {"analyzer": 111, "stories": 222},
        },
        "cost": {"per_run_token_cap": 500_000},
    })
    p = tmp_path / "settings.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr("agent_harness.config.SETTINGS_PATH", p)
    from agent_harness.config import load_settings
    s = load_settings()
    assert s.timeouts.per_call_seconds == 45
    assert s.timeouts.per_stage_seconds["analyzer"] == 111
    assert s.timeouts.per_stage_seconds["stories"] == 222
    # Roles missing from YAML fall back to built-in defaults via timeout_for.
    assert s.timeout_for("stories") == 222
    assert s.timeout_for("reviewer") == 600   # default fallback
    assert s.cost.per_run_token_cap == 500_000


def test_load_settings_missing_blocks_uses_defaults(tmp_path, monkeypatch):
    p = tmp_path / "settings.yaml"
    p.write_text(yaml.safe_dump({"default_model": "gpt-5.4-mini"}), encoding="utf-8")
    monkeypatch.setattr("agent_harness.config.SETTINGS_PATH", p)
    from agent_harness.config import load_settings
    s = load_settings()
    assert s.timeouts.per_call_seconds == 120
    assert s.cost.per_run_token_cap is None
```

- [ ] **Step 2:** Run. Expect ImportError or AttributeError.

- [ ] **Step 3: Extend `agent_harness/config.py`**

Open the file. Add the two new dataclasses near the other `@dataclass` blocks (above `Settings`):

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

Extend `Settings`:

```python
@dataclass
class Settings:
    ...existing fields...
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    cost: CostConfig = field(default_factory=CostConfig)

    def model_for_role(self, role: str) -> str:
        return self.models.get(role, self.default_model)

    def active_profile(self) -> SpeedProfile:
        return self.speed_profiles.get(self.default_profile, list(self.speed_profiles.values())[0])

    def timeout_for(self, role: str) -> int:
        return self.timeouts.per_stage_seconds.get(role, 600)
```

In `load_settings()`, add parsing just before the final `return Settings(...)`:

```python
    timeouts_raw = raw.get("timeouts", {})
    timeouts_cfg = TimeoutConfig(
        per_call_seconds=int(timeouts_raw.get("per_call_seconds", 120)),
        per_stage_seconds={**TimeoutConfig().per_stage_seconds,
                           **timeouts_raw.get("per_stage_seconds", {})},
    )
    cost_raw = raw.get("cost", {})
    cost_cfg = CostConfig(
        per_run_token_cap=cost_raw.get("per_run_token_cap") if cost_raw.get("per_run_token_cap") is not None else None,
    )
```

And in the final `Settings(...)` constructor, pass `timeouts=timeouts_cfg, cost=cost_cfg`.

- [ ] **Step 4: Extend `config/settings.yaml`**

Append at the end:

```yaml

# Operator-safety knobs (sub-project D.2)
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

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_settings_timeouts_cost.py tests/test_config.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_harness/config.py config/settings.yaml tests/test_settings_timeouts_cost.py
git commit -m "feat(config): TimeoutConfig + CostConfig with YAML loading and timeout_for helper"
```

---

## Task 3: `base.run_with_retry` — per-call timeout + usage accounting

**Files:**
- Modify: `agent_harness/base.py`
- Test: `tests/test_run_with_retry_timeout.py`
- Test: `tests/test_run_with_retry_usage.py`

- [ ] **Step 1: Write the timeout test**

```python
# tests/test_run_with_retry_timeout.py
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_harness.base import run_with_retry


class _Agent:
    def __init__(self, delays: list[float], text: str = "ok"):
        self._delays = list(delays)
        self._text = text

    async def run(self, message: str):
        delay = self._delays.pop(0)
        await asyncio.sleep(delay)
        return SimpleNamespace(text=self._text, usage=None)


def _settings_with_timeouts(per_call: int):
    from agent_harness.config import Settings, TimeoutConfig
    return Settings(timeouts=TimeoutConfig(per_call_seconds=per_call))


@pytest.mark.asyncio
async def test_per_call_timeout_retries_then_succeeds():
    agent = _Agent(delays=[2.0, 0.0], text="hi")  # first: slow, second: fast
    with patch("agent_harness.base.get_settings",
               return_value=_settings_with_timeouts(per_call=1)):
        # Compress backoff sleep so the test stays fast.
        with patch("agent_harness.base.asyncio.sleep",
                   new=lambda *_, **__: asyncio.sleep(0)):
            result = await run_with_retry(agent, "msg", max_retries=3)
    assert result == "hi"


@pytest.mark.asyncio
async def test_per_call_timeout_exhausts_retries_and_raises():
    agent = _Agent(delays=[2.0, 2.0, 2.0])
    with patch("agent_harness.base.get_settings",
               return_value=_settings_with_timeouts(per_call=1)):
        with patch("agent_harness.base.asyncio.sleep",
                   new=lambda *_, **__: asyncio.sleep(0)):
            with pytest.raises(Exception) as exc:
                await run_with_retry(agent, "msg", max_retries=3)
    assert "Agent failed" in str(exc.value) or "timeout" in str(exc.value).lower()
```

- [ ] **Step 2: Write the usage test**

```python
# tests/test_run_with_retry_usage.py
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_harness import observability
from agent_harness.base import run_with_retry


class _Agent:
    def __init__(self, text: str, usage):
        self._text = text
        self._usage = usage

    async def run(self, message: str):
        return SimpleNamespace(text=self._text, usage=self._usage)


def _settings_with_cap(cap: int | None, per_call: int = 30):
    from agent_harness.config import Settings, TimeoutConfig, CostConfig
    return Settings(
        timeouts=TimeoutConfig(per_call_seconds=per_call),
        cost=CostConfig(per_run_token_cap=cap),
    )


@pytest.mark.asyncio
async def test_usage_from_response_credits_counter():
    counter = observability.start_run(cap_tokens=None)
    agent = _Agent("hello", SimpleNamespace(input_tokens=100, output_tokens=50))
    with patch("agent_harness.base.get_settings",
               return_value=_settings_with_cap(None)):
        await run_with_retry(agent, "msg")
    assert counter.input_tokens == 100
    assert counter.output_tokens == 50


@pytest.mark.asyncio
async def test_usage_fallback_heuristic_when_no_usage_field():
    counter = observability.start_run(cap_tokens=None)
    agent = _Agent("x" * 400, usage=None)  # 100 tokens by char/4
    with patch("agent_harness.base.get_settings",
               return_value=_settings_with_cap(None)):
        await run_with_retry(agent, "y" * 40)  # 10 tokens by char/4
    assert counter.input_tokens == 10
    assert counter.output_tokens == 100


@pytest.mark.asyncio
async def test_token_budget_exceeded_propagates():
    observability.start_run(cap_tokens=50)
    agent = _Agent("hi", SimpleNamespace(input_tokens=60, output_tokens=0))
    with patch("agent_harness.base.get_settings",
               return_value=_settings_with_cap(50)):
        with pytest.raises(observability.TokenBudgetExceeded):
            await run_with_retry(agent, "msg")
```

- [ ] **Step 3:** Run both test files. Expect failures (timeout path missing, usage path missing).

- [ ] **Step 4: Modify `agent_harness/base.py::run_with_retry`**

Replace the existing body with:

```python
async def run_with_retry(agent: "Agent", message: str, max_retries: int = 3) -> str:
    """Run an agent with exponential backoff on rate-limit / timeout errors."""
    from . import observability  # local import to avoid cycles

    timeout = get_settings().timeouts.per_call_seconds

    for attempt in range(max_retries):
        try:
            result = await asyncio.wait_for(agent.run(message), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("agent.run timeout after %ds (attempt %d/%d)",
                            timeout, attempt + 1, max_retries)
            if attempt == max_retries - 1:
                break
            await asyncio.sleep(2 ** attempt)
            continue
        except Exception as e:
            error_str = str(e).lower()

            if "rate_limit" in error_str or "429" in error_str:
                wait = (2 ** attempt) + (asyncio.get_event_loop().time() % 1)
                logger.warning("Rate limited (attempt %d/%d), waiting %.1fs",
                                attempt + 1, max_retries, wait)
                await asyncio.sleep(wait)
                continue

            if "context_length" in error_str or "token" in error_str:
                logger.warning("Token limit hit — retrying with truncated context")
                message = message[:int(len(message) * 0.7)]
                continue

            logger.error("Agent error (attempt %d/%d): %s",
                          attempt + 1, max_retries, e)
            if attempt == max_retries - 1:
                raise

        else:
            input_tokens, output_tokens = _extract_usage(result, message)
            observability.charge(input_tokens, output_tokens)  # may raise TokenBudgetExceeded
            return result.text

    raise RuntimeError(f"Agent failed after {max_retries} retries")


def _extract_usage(result, message: str) -> tuple[int, int]:
    """Pull usage from the agent result if available; else char/4 heuristic."""
    usage = getattr(result, "usage", None)
    if usage is not None:
        in_t = int(getattr(usage, "input_tokens", 0) or 0)
        out_t = int(getattr(usage, "output_tokens", 0) or 0)
        if in_t or out_t:
            return in_t, out_t
    return len(message) // 4, len(getattr(result, "text", "")) // 4
```

Note the structural change: success path moved into `else:` block of the `try/except`, so token charging only happens on success (not after retry). Timeout case falls through the `for` loop to the final `raise RuntimeError`.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_run_with_retry_timeout.py tests/test_run_with_retry_usage.py -v`
Expected: 5 PASS (2 timeout + 3 usage).

- [ ] **Step 6: Regression**

Run: `python3 -m pytest tests/test_discovery_e2e.py tests/test_fanout_e2e.py tests/test_eval_cli.py -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add agent_harness/base.py tests/test_run_with_retry_timeout.py tests/test_run_with_retry_usage.py
git commit -m "feat(base): run_with_retry wraps each call in asyncio.wait_for and charges TokenCounter"
```

---

## Task 4: `MigrationPipeline.run` — per-stage timeout wrappers + `set_stage`

**Files:**
- Modify: `agent_harness/pipeline.py`
- Test: `tests/test_pipeline_stage_timeout.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_stage_timeout.py
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.pipeline import MigrationPipeline


def _slow(seconds: float):
    async def _fn(*_, **__):
        await asyncio.sleep(seconds)
        return "analysis"
    return _fn


@pytest.mark.asyncio
async def test_pipeline_analyzer_timeout_marks_blocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src" / "lambda" / "orders").mkdir(parents=True)
    (tmp_path / "src" / "lambda" / "orders" / "handler.py").write_text("pass\n")
    pipe = MigrationPipeline(project_root=str(tmp_path))
    await pipe.initialize()

    # Compress analyzer timeout to 0.05s; stage sleeps 1s.
    from agent_harness.config import Settings, TimeoutConfig, QualityConfig
    tight = Settings(
        timeouts=TimeoutConfig(per_call_seconds=30,
                                per_stage_seconds={"analyzer": 0.05,
                                                    "coder": 30, "tester": 30,
                                                    "reviewer": 30, "security": 30}),
        quality=QualityConfig(),
    )
    pipe.settings = tight  # inject

    with patch("agent_harness.pipeline.analyze_module", new=_slow(1.0)):
        result = await pipe.run(module="orders", language="python")

    assert result.status == "blocked"
    assert "timed out" in (result.message or "").lower()
```

- [ ] **Step 2:** Run. Expect `result.status == "completed"` or the mocked sleep causing the test to hang; either way, not matching `blocked`.

- [ ] **Step 3: Wrap stage calls in `MigrationPipeline.run`**

Open `agent_harness/pipeline.py`. Locate `MigrationPipeline.run`. After normalising `source_paths`/`context_paths`/`repo_root`/`module_path`, and just before Gate 1:

- Add `from . import observability` at the top of the file (alongside existing imports).
- Define a small helper inside or alongside the class:

```python
async def _with_stage_timeout(self, role: str, coro):
    timeout = self.settings.timeout_for(role)
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        raise _StageTimeout(role, timeout)


class _StageTimeout(RuntimeError):
    def __init__(self, role: str, seconds: int):
        super().__init__(f"{role} timed out after {seconds}s")
        self.role = role
        self.seconds = seconds
```

Wrap each stage call. Example for analyzer:

```python
            observability.set_stage("analyzer", attempt=1)
            logger.info("[Gate 1] Running analyzer for %s", module)
            cached = self.repo.get_cached_analysis(module)
            if cached:
                analysis = cached.get("analysis_text", "")
            else:
                try:
                    analysis = await self._with_stage_timeout(
                        "analyzer",
                        analyze_module(
                            module=module, language=language, source_dir=source_dir,
                            source_paths=source_paths, context_paths=context_paths,
                            repo_root=repo_root, module_path=module_path,
                        ),
                    )
                except _StageTimeout as exc:
                    self.repo.complete_run(run_id, "blocked", str(exc))
                    return PipelineResult(
                        module=module, status="blocked", message=str(exc),
                        gates_failed=[1],
                    )
                self.repo.cache_analysis(module,
                    {"analysis_text": analysis}, score=0, level="UNKNOWN")
```

Do the same structural change (wrap in `_with_stage_timeout`, catch `_StageTimeout`, return `PipelineResult(status="blocked")`) for every other agent call inside `run`:
- `migrate_module` → stage role `"coder"`; on timeout return blocked with `gates_failed=[3]`.
- `evaluate_module` → `"tester"`; `gates_failed=[4, 5]`.
- `review_module` → `"reviewer"`; `gates_failed=[6]`.
- `security_review` → `"security"`; `gates_failed=[7]`.

Before each of those stages, also call `observability.set_stage(role, attempt=...)`.

- [ ] **Step 4:** Run test.

Run: `python3 -m pytest tests/test_pipeline_stage_timeout.py tests/test_pipeline_paths.py tests/test_pipeline_agents_md.py -v`
Expected: all PASS.

- [ ] **Step 5: Regression**

Run: `python3 -m pytest tests/test_fanout_e2e.py tests/test_eval_cli.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_harness/pipeline.py tests/test_pipeline_stage_timeout.py
git commit -m "feat(pipeline): per-stage timeout wrappers; set_stage before each stage"
```

---

## Task 5: Discovery `run_stage` — optional `stage_timeout`

**Files:**
- Modify: `agent_harness/discovery/workflow.py`
- Test: `tests/test_discovery_stage_timeout.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_stage_timeout.py
import asyncio
from unittest.mock import AsyncMock

import pytest

from agent_harness.discovery.artifacts import CriticReport
from agent_harness.discovery.workflow import run_stage
from agent_harness.persistence.repository import MigrationRepository


@pytest.fixture
def repo(tmp_path):
    r = MigrationRepository(db_path=tmp_path / "t.db")
    r.initialize()
    r.create_discovery_run("synth")
    return r


@pytest.mark.asyncio
async def test_stage_timeout_treated_as_failed_critic(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)
    call_count = {"n": 0}

    async def slow_produce(feedback: str) -> str:
        call_count["n"] += 1
        await asyncio.sleep(1.0)
        return "never"

    def critic(result: str, ctx: dict) -> CriticReport:
        return CriticReport(verdict="PASS", reasons=[], suggestions=[])

    artifact = tmp_path / "discovery" / "synth" / "scanner.txt"
    with pytest.raises(RuntimeError, match="blocked"):
        await run_stage(
            repo=repo, repo_id="synth", stage_name="scanner",
            produce=slow_produce, critic=critic,
            artifact_path=artifact, input_hash="h1",
            stage_timeout=0.05,
        )
    # Three attempts, each timing out.
    assert call_count["n"] == 3


@pytest.mark.asyncio
async def test_stage_timeout_none_keeps_old_behaviour(tmp_path, monkeypatch, repo):
    monkeypatch.chdir(tmp_path)

    async def fast_produce(feedback: str) -> str:
        return "ok"

    def critic(result: str, ctx: dict) -> CriticReport:
        return CriticReport(verdict="PASS", reasons=[], suggestions=[])

    artifact = tmp_path / "discovery" / "synth" / "scanner.txt"
    out = await run_stage(
        repo=repo, repo_id="synth", stage_name="scanner",
        produce=fast_produce, critic=critic,
        artifact_path=artifact, input_hash="h1",
        stage_timeout=None,
    )
    assert out == "ok"
```

- [ ] **Step 2:** Run. Expect TypeError (`run_stage` does not accept `stage_timeout`).

- [ ] **Step 3: Extend `run_stage`**

Open `agent_harness/discovery/workflow.py`. Locate `async def run_stage(...)`. Add `stage_timeout: float | None = None` to the signature. Inside the attempt loop, wrap the `await produce(feedback)` call:

```python
    from agent_harness import observability

    ...
    feedback = ""
    last: CriticReport | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        observability.set_stage(stage_name, attempt)
        logger.info("[%s] attempt %d/%d", stage_name, attempt, MAX_ATTEMPTS)
        try:
            if stage_timeout is not None:
                result = await asyncio.wait_for(produce(feedback), timeout=stage_timeout)
            else:
                result = await produce(feedback)
        except asyncio.TimeoutError:
            report = CriticReport(
                verdict="FAIL",
                reasons=[f"stage timed out after {stage_timeout}s"],
                suggestions=["Investigate the stall or raise the per-stage timeout."],
            )
            feedback = "\n\n## Critic feedback (apply this):\n" + "\n".join(
                f"- {r}" for r in report.reasons)
            last = report
            continue
        report = critic(result, critic_context or {})
        ...
```

Ensure `import asyncio` is at the top of the file (already is — verify).

- [ ] **Step 4: Thread `stage_timeout` into every stage in `run_discovery`**

Still in `workflow.py`, inside `run_discovery`, for each of the five `run_stage(...)` invocations (scanner, grapher, brd, architect, stories), add:

```python
stage_timeout=repo_settings_lookup(...)   # see below
```

Concretely, fetch once at the top of `run_discovery`:

```python
    from ..config import load_settings
    _settings = load_settings()
```

Then pass to each call:

```python
    raw_inv = await run_stage(..., inv_hash,
                               stage_timeout=_settings.timeout_for("scanner"))
    ...
    raw_graph = await run_stage(..., g_hash,
                                 stage_timeout=_settings.timeout_for("grapher"))
    ...
    await run_stage(..., b_hash,
                     stage_timeout=_settings.timeout_for("brd"))
    ...
    await run_stage(..., d_hash,
                     stage_timeout=_settings.timeout_for("architect"))
    ...
    await run_stage(..., s_hash,
                     stage_timeout=_settings.timeout_for("stories"))
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/test_discovery_stage_timeout.py tests/test_discovery_workflow.py tests/test_discovery_e2e.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_harness/discovery/workflow.py tests/test_discovery_stage_timeout.py
git commit -m "feat(discovery): run_stage accepts stage_timeout; run_discovery threads per-stage timeouts"
```

---

## Task 6: Orchestrator — trace + token counter on every endpoint; 402 mapping; lifespan logging

**Files:**
- Modify: `agent_harness/orchestrator/api.py`
- Test: `tests/test_token_budget_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_token_budget_api.py
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    from agent_harness.orchestrator import api as api_mod
    api_mod._pipeline = None
    api_mod._ado = None
    from agent_harness.persistence.repository import MigrationRepository
    api_mod._discovery_repo = MigrationRepository(db_path=tmp_path / "disc.db")
    api_mod._discovery_repo.initialize()
    return TestClient(api_mod.app)


def test_discover_surfaces_token_budget_exceeded_as_402(client, tmp_path):
    repo_root = tmp_path / "synth"
    repo_root.mkdir()

    from agent_harness import observability

    async def raise_budget(**_):
        raise observability.TokenBudgetExceeded("token cap 10 exceeded (total=11)")

    with patch("agent_harness.discovery.workflow.run_discovery", new=AsyncMock(side_effect=raise_budget)):
        resp = client.post("/discover", json={
            "repo_id": "synth", "repo_path": str(repo_root),
        })
    assert resp.status_code == 402
    assert "token cap" in resp.json()["detail"]


def test_discover_sets_trace_and_token_counter(client, tmp_path):
    """Entry point seeds a trace id and a TokenCounter before invoking work."""
    repo_root = tmp_path / "synth"
    repo_root.mkdir()

    captured = {}

    async def capture_ctx(**_):
        from agent_harness import observability
        captured["trace"] = observability.TRACE_ID.get()
        captured["counter"] = observability.TOKEN_COUNTER.get()
        return {"status": "ok", "stages": [], "artifacts": {}}

    with patch("agent_harness.discovery.workflow.run_discovery", new=AsyncMock(side_effect=capture_ctx)):
        resp = client.post("/discover", json={
            "repo_id": "synth", "repo_path": str(repo_root),
        })
    assert resp.status_code == 200
    assert captured["trace"].startswith("discover-")
    assert captured["counter"] is not None
```

- [ ] **Step 2:** Run. Expect `502`/`500` (unhandled exception) or missing trace context.

- [ ] **Step 3: Modify `orchestrator/api.py`**

At the top of the file, add the observability import:

```python
from agent_harness import observability
```

In `lifespan`, replace `logging.basicConfig(...)` (if present elsewhere in the file) with:

```python
observability.init_logging(os.environ.get("LOG_FORMAT", "text"))
```

For every endpoint that performs work (not `/health`), seed trace + counter. The canonical pattern:

```python
@app.post("/discover", response_model=DiscoverResponse)
async def discover(req: DiscoverRequest):
    settings = load_settings()  # re-read each call so operators can hot-edit
    observability.new_trace("discover")
    observability.start_run(settings.cost.per_run_token_cap)

    if not os.path.isdir(req.repo_path):
        raise HTTPException(404, f"repo_path not found: {req.repo_path}")
    try:
        result = await discovery_workflow.run_discovery(
            repo_id=req.repo_id, repo_path=req.repo_path, repo=_discovery_repo,
        )
    except observability.TokenBudgetExceeded as exc:
        raise HTTPException(402, str(exc))
    except RuntimeError as e:
        return DiscoverResponse(status="blocked", repo_id=req.repo_id, message=str(e))
    return DiscoverResponse(
        status=result["status"], repo_id=req.repo_id,
        artifacts=result.get("artifacts", {}), stages=result.get("stages", []),
    )
```

Repeat the `new_trace(...)` + `start_run(settings.cost.per_run_token_cap)` + `except observability.TokenBudgetExceeded → HTTPException(402)` pattern on:
- `/migrate` (trace prefix `"migrate"`)
- `/migrate/sync` (prefix `"migrate-sync"`)
- `/plan` (prefix `"plan"`)
- `/approve/backlog/{repo_id}` (prefix `"approve"`)
- `/migrate-repo` (prefix `"migrate-repo"`)
- `/migrate-repo/sync` (prefix `"migrate-repo-sync"`)
- `GET /discover/{repo_id}` (prefix `"discover-status"`)
- `GET /status/{module}` (prefix `"status"`)
- `GET /migrate-repo/{repo_id}` (prefix `"migrate-repo-status"`)

`load_settings()` is already imported; add it at the top if not. The pattern is formulaic — the goal is every public endpoint produces traceable logs.

- [ ] **Step 4:** Run the new test and regressions.

Run: `python3 -m pytest tests/test_token_budget_api.py tests/test_discovery_api.py tests/test_migrate_repo_api.py tests/test_migrate_request_paths.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/orchestrator/api.py tests/test_token_budget_api.py
git commit -m "feat(orchestrator): every endpoint seeds trace+counter; TokenBudgetExceeded→402; lifespan installs logging"
```

---

## Task 7: JSON logging smoke test

**Files:**
- Test: `tests/test_logging_json.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_logging_json.py
import json
import logging
from io import StringIO

from agent_harness import observability


def test_json_log_line_is_valid_and_populated(monkeypatch):
    observability.init_logging("json")
    root = logging.getLogger()
    handler = root.handlers[0]
    buf = StringIO()
    handler.stream = buf

    observability.new_trace("sanity")
    observability.set_stage("tester", 2)
    logging.getLogger("eval").warning("something happened")

    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    assert lines, "no log output captured"
    data = json.loads(lines[-1])
    assert data["level"] == "WARNING"
    assert data["logger"] == "eval"
    assert data["message"] == "something happened"
    assert data["trace_id"].startswith("sanity-")
    assert data["stage"] == "tester"
    assert data["attempt"] == 2


def test_text_log_line_contains_trace_and_stage(monkeypatch):
    observability.init_logging("text")
    root = logging.getLogger()
    handler = root.handlers[0]
    buf = StringIO()
    handler.stream = buf

    observability.new_trace("sanity")
    observability.set_stage("coder", 1)
    logging.getLogger("pipeline").info("running coder")

    out = buf.getvalue()
    assert "trace=sanity-" in out
    assert "stage=coder" in out
    assert "attempt=1" in out
    assert "running coder" in out
```

- [ ] **Step 2:** Run: `python3 -m pytest tests/test_logging_json.py -v`
Expected: 2 PASS (Task 1 already added `init_logging`).

- [ ] **Step 3: Commit**

```bash
git add tests/test_logging_json.py
git commit -m "test(observability): smoke tests for JSON and text log formats"
```

---

## Task 8: README — operator knobs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append section**

Append to `ms-agent-harness/README.md`:

```markdown

## Operator knobs (sub-project D.2)

### Timeouts
`config/settings.yaml::timeouts`:

- `per_call_seconds` (default 120) — wallclock cap on each `agent.run` call.
  Exceeding it retries with backoff; after `max_retries` the stage surfaces.
- `per_stage_seconds.<role>` — wallclock cap on the full stage (all attempts
  combined for discovery; single attempt for migration). Exceeding it marks
  the stage blocked.

### Token budget
`config/settings.yaml::cost.per_run_token_cap` — integer (null disables).
When the cumulative input+output tokens of a single `/discover`, `/plan`,
`/migrate`, `/migrate/sync`, `/migrate-repo`, or `/migrate-repo/sync`
invocation cross the cap, the in-flight run aborts with HTTP 402 Payment
Required. Partial artifacts on disk are preserved for inspection.

Token usage is pulled from `result.usage.input_tokens` /
`result.usage.output_tokens` when the SDK provides them; otherwise
approximated as `len(text) // 4`.

### Structured logging
Every log line is tagged with the current run's `trace_id`, `stage`, and
`attempt` via a logging Filter reading ContextVars. Text format (default)
inlines the tags; set `LOG_FORMAT=json` for JSON lines to stdout suitable
for ingestion.

```
LOG_FORMAT=json uvicorn agent_harness.orchestrator.api:app
```

Example JSON line:

```
{"ts": "2026-04-14T14:00:00Z", "level": "INFO", "logger": "pipeline",
 "trace_id": "migrate-ab12cd34", "stage": "analyzer", "attempt": 1,
 "message": "[Gate 1] Running analyzer for orders"}
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): document D.2 operator knobs (timeouts, token cap, JSON logging)"
```

---

## Self-Review Notes

- **Spec coverage:**
  - §4.1 `observability.py` — Task 1.
  - §4.2 Settings `timeouts` / `cost` blocks — Task 2.
  - §4.3 `run_with_retry` per-call timeout + usage accounting — Task 3.
  - §4.4 Migration per-stage timeouts — Task 4.
  - §4.4 Discovery per-stage timeouts via `run_stage` — Task 5.
  - §4.5 Orchestrator trace + start_run + 402 + lifespan — Task 6.
  - §4.6 settings.yaml YAML additions — Task 2 Step 4.
  - §5.1 JSON log shape — Task 1 (implementation) + Task 7 (explicit smoke test).
  - §5.2 402 mapping — Task 6 test.
  - §7 error handling — Tasks 3/4/5/6 each exercise the relevant row.
  - §8 testing — every bullet has a matching test file.
- **Placeholder scan:** No TBDs. The `/status/{module}` and `GET /discover/{repo_id}` endpoints get trace context in Task 6 mainly for consistency; they don't execute work that can cross the token cap, but the seed is cheap and keeps log correlation uniform.
- **Type consistency:** `TokenCounter`, `TokenBudgetExceeded`, `new_trace`, `set_stage`, `start_run`, `charge`, `init_logging` consistently named across Tasks 1, 3, 4, 5, 6, 7. `TimeoutConfig.per_call_seconds` / `per_stage_seconds` / `CostConfig.per_run_token_cap` consistent between config-loading test (Task 2), `run_with_retry` (Task 3), and API (Task 6). `Settings.timeout_for(role)` called consistently in Tasks 4 and 5.
- **Back-compat:** `per_run_token_cap=null` → `start_run(None)` → `charge()` never raises; pre-existing runs behave identically. All timeout kwargs default to values that permit existing tests to pass. `run_stage(stage_timeout=None)` preserves old behaviour verbatim.
