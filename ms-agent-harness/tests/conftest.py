"""
Shared test fixtures for ms-agent-harness.

Provides temp directories, sample code, and Settings objects.
Also installs a mock for the `agent_framework` module so that source
files using `@tool` can be imported without the real SDK installed.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock agent_framework BEFORE any agents.* imports so the @tool decorator
# is a harmless pass-through.  This block runs at import time of conftest.
# ---------------------------------------------------------------------------
class _MockModule(types.ModuleType):
    """Module that returns a MagicMock for any attribute access."""

    def __getattr__(self, name):
        if name == "tool":
            return lambda **kwargs: (lambda fn: fn)
        m = MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, m)
        return m


_af = _MockModule("agent_framework")
sys.modules.setdefault("agent_framework", _af)
for _sub in (
    "agent_framework_foundry",
    "agent_framework.foundry",
    "agent_framework_azure_ai",
):
    sys.modules.setdefault(_sub, _MockModule(_sub))

# Now safe to import project modules
from agent_harness.config import Settings, SpeedProfile, ChunkingConfig, QualityConfig, RateLimits

# Root of project (one level up from tests/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_LAMBDA = PROJECT_ROOT / "sample" / "lambda" / "handler.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory (alias for clarity)."""
    return tmp_path


@pytest.fixture
def sample_lambda_code():
    """Return the full text of sample/lambda/handler.py."""
    return SAMPLE_LAMBDA.read_text(encoding="utf-8")


@pytest.fixture
def sample_lambda_path():
    """Return the path to sample/lambda/handler.py."""
    return str(SAMPLE_LAMBDA)


@pytest.fixture
def sample_settings():
    """Return a Settings object with sensible test defaults (no YAML load)."""
    return Settings(
        foundry_endpoint="https://test.openai.azure.com",
        default_model="gpt-4o",
        models={
            "analyzer": "gpt-4o",
            "coder": "gpt-4o-mini",
            "tester": "gpt-4o-mini",
            "reviewer": "gpt-4o",
        },
        speed_profiles={
            "balanced": SpeedProfile(
                name="balanced",
                description="Default test profile",
                token_ceiling=100000,
                reasoning_effort="medium",
                max_parallel_chunks=3,
                complexity_multipliers={"low": 1.5, "medium": 2.5, "high": 3.5},
            ),
        },
        default_profile="balanced",
        rate_limits=RateLimits(),
        chunking=ChunkingConfig(),
        quality=QualityConfig(),
    )
