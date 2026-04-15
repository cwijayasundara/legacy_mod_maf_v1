import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_harness.base import run_with_retry

# Capture the real asyncio.sleep so test patches don't recurse into themselves.
_real_sleep = asyncio.sleep


class _Agent:
    def __init__(self, delays: list[float], text: str = "ok"):
        self._delays = list(delays)
        self._text = text

    async def run(self, message: str):
        delay = self._delays.pop(0)
        await _real_sleep(delay)
        return SimpleNamespace(text=self._text, usage=None)


def _settings_with_timeouts(per_call: int):
    from agent_harness.config import Settings, TimeoutConfig, RateLimits
    return Settings(
        timeouts=TimeoutConfig(per_call_seconds=per_call),
        rate_limits=RateLimits(requests_per_minute=1000, sliding_window_seconds=1),
    )


@pytest.mark.asyncio
async def test_per_call_timeout_retries_then_succeeds():
    agent = _Agent(delays=[2.0, 0.0], text="hi")
    with patch("agent_harness.base.get_settings",
               return_value=_settings_with_timeouts(per_call=1)):
        with patch("agent_harness.base.asyncio.sleep",
                   new=lambda *_, **__: _real_sleep(0)):
            result = await run_with_retry(agent, "msg", max_retries=3)
    assert result == "hi"


@pytest.mark.asyncio
async def test_per_call_timeout_exhausts_retries_and_raises():
    agent = _Agent(delays=[2.0, 2.0, 2.0])
    with patch("agent_harness.base.get_settings",
               return_value=_settings_with_timeouts(per_call=1)):
        with patch("agent_harness.base.asyncio.sleep",
                   new=lambda *_, **__: _real_sleep(0)):
            with pytest.raises(Exception) as exc:
                await run_with_retry(agent, "msg", max_retries=3)
    assert "Agent failed" in str(exc.value) or "timeout" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_concurrent_calls_share_request_window():
    from agent_harness.config import Settings, TimeoutConfig, RateLimits

    class _FastAgent:
        def __init__(self, marks: list[float]):
            self._marks = marks

        async def run(self, message: str):
            self._marks.append(time.monotonic())
            return SimpleNamespace(text="ok", usage=None)

    marks: list[float] = []
    settings = Settings(
        timeouts=TimeoutConfig(per_call_seconds=1),
        rate_limits=RateLimits(requests_per_minute=1, sliding_window_seconds=0.2),
    )

    with patch("agent_harness.base._request_gate", None), \
            patch("agent_harness.base._request_gate_signature", None), \
            patch("agent_harness.base.get_settings", return_value=settings), \
            patch.dict("os.environ", {"OPENAI_CALL_CONCURRENCY": "4"}, clear=False):
        await asyncio.gather(
            run_with_retry(_FastAgent(marks), "one", max_retries=1),
            run_with_retry(_FastAgent(marks), "two", max_retries=1),
        )

    assert len(marks) == 2
    assert marks[1] - marks[0] >= 0.18
