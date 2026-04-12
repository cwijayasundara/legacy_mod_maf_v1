"""Tests for copilot_runner.py — no CLI or LLM calls."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.copilot_runner import CopilotRunner


def test_is_available_false():
    with patch("shutil.which", return_value=None):
        runner = CopilotRunner()
        assert runner.is_available() is False


def test_is_available_true():
    with patch("shutil.which", return_value="/usr/bin/copilot"):
        runner = CopilotRunner()
        assert runner.is_available() is True


def test_build_env_byok():
    runner = CopilotRunner(
        provider_type="azure",
        provider_url="https://my-endpoint.openai.azure.com",
        api_key="test-key",
        model="gpt-4o",
        offline=True,
    )
    env = runner._build_env()
    assert env["COPILOT_PROVIDER_TYPE"] == "azure"
    assert env["COPILOT_PROVIDER_BASE_URL"] == "https://my-endpoint.openai.azure.com"
    assert env["COPILOT_PROVIDER_API_KEY"] == "test-key"
    assert env["COPILOT_MODEL"] == "gpt-4o"
    assert env["COPILOT_OFFLINE"] == "true"


def test_build_env_no_byok():
    runner = CopilotRunner(provider_type="", provider_url="", api_key="", model="")
    env = runner._build_env()
    assert "COPILOT_PROVIDER_TYPE" not in env or env.get("COPILOT_PROVIDER_TYPE") == ""


def test_timeout_by_language():
    runner = CopilotRunner()
    assert runner._timeouts.get("java", 3600) >= 3600
    assert runner._timeouts.get("python", 3600) == 3600
