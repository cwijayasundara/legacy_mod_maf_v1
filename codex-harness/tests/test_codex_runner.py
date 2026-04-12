"""Tests for orchestrator/codex_runner.py — no CLI or LLM calls."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "harness", "orchestrator"))

from codex_runner import CodexRunner, LANGUAGE_TIMEOUTS, DEFAULT_TIMEOUT


def _make_runner():
    return CodexRunner(
        model="o4-mini",
        api_base="https://my-aoai.openai.azure.com",
        api_key="test-key-123",
        project_root="/tmp/fake-project",
    )


# ---------- tests ----------


def test_is_available_false():
    """When codex is not on PATH, is_available() should return False."""
    runner = _make_runner()
    with patch("shutil.which", return_value=None):
        assert runner.is_available() is False


def test_is_available_true():
    """When codex IS on PATH, is_available() should return True."""
    runner = _make_runner()
    with patch("shutil.which", return_value="/usr/local/bin/codex"):
        assert runner.is_available() is True


def test_build_env():
    """_build_env should include OPENAI_API_KEY and CODEX_API_BASE when set."""
    runner = _make_runner()
    env = runner._build_env()

    assert env["OPENAI_API_KEY"] == "test-key-123"
    assert env["CODEX_API_BASE"] == "https://my-aoai.openai.azure.com"
    assert env["OPENAI_BASE_URL"] == "https://my-aoai.openai.azure.com"


def test_build_env_no_base():
    """When api_base is empty, the runner should NOT inject CODEX_API_BASE."""
    # Remove CODEX_API_BASE from os.environ if it exists so the test is clean
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CODEX_API_BASE", None)
        os.environ.pop("OPENAI_BASE_URL", None)
        runner = CodexRunner(
            model="o4-mini",
            api_base="",
            api_key="key",
            project_root="/tmp",
        )
        env = runner._build_env()
        assert env.get("OPENAI_API_KEY") == "key"
        assert "CODEX_API_BASE" not in env
        assert "OPENAI_BASE_URL" not in env


def test_timeout_by_language():
    """Java should get 5400s, Python should get 3600s, unknown falls back to default."""
    assert LANGUAGE_TIMEOUTS["java"] == 5400
    assert LANGUAGE_TIMEOUTS["python"] == 3600
    assert LANGUAGE_TIMEOUTS["csharp"] == 5400
    assert LANGUAGE_TIMEOUTS["node"] == 3600
    # Unknown language should use DEFAULT_TIMEOUT
    assert LANGUAGE_TIMEOUTS.get("go", DEFAULT_TIMEOUT) == DEFAULT_TIMEOUT
    assert DEFAULT_TIMEOUT == 3600
