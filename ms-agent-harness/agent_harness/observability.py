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
