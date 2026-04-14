import json
import logging
from io import StringIO

from agent_harness import observability


def test_json_log_line_is_valid_and_populated():
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


def test_text_log_line_contains_trace_and_stage():
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
