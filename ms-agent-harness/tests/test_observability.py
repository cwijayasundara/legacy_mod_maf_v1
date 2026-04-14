import json
import logging
from io import StringIO

import pytest


def test_new_trace_sets_context_and_returns_id():
    from agent_harness.observability import new_trace, TRACE_ID
    tid = new_trace("discover")
    assert tid.startswith("discover-")
    assert len(tid.split("-", 1)[1]) == 8
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


def test_charge_without_counter_is_noop():
    from agent_harness.observability import charge, TOKEN_COUNTER
    TOKEN_COUNTER.set(None)
    charge(1000, 1000)


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
    assert fmt.__class__.__name__ == "Formatter"


def test_init_logging_is_idempotent():
    from agent_harness import observability
    observability.init_logging("text")
    observability.init_logging("json")
    root = logging.getLogger()
    assert len(root.handlers) == 1
