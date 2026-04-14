import asyncio
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
    from agent_harness.config import Settings, TimeoutConfig
    return Settings(timeouts=TimeoutConfig(per_call_seconds=per_call))


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
