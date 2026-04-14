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
    agent = _Agent("x" * 400, usage=None)
    with patch("agent_harness.base.get_settings",
               return_value=_settings_with_cap(None)):
        await run_with_retry(agent, "y" * 40)
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
