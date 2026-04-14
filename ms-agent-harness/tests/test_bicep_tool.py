import subprocess
from unittest.mock import patch

from agent_harness.tools.bicep_tool import validate_bicep


def _fake_run(returncode=0, stdout="", stderr=""):
    class R:
        pass
    r = R()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def test_valid_bicep_transpiles(tmp_path):
    f = tmp_path / "main.bicep"
    f.write_text("param name string\n")
    with patch("agent_harness.tools.bicep_tool.subprocess.run",
               return_value=_fake_run(returncode=0)):
        assert validate_bicep(str(f)) == "VALID"


def test_invalid_bicep_returns_stderr(tmp_path):
    f = tmp_path / "main.bicep"
    f.write_text("broken\n")
    with patch("agent_harness.tools.bicep_tool.subprocess.run",
               return_value=_fake_run(returncode=1,
                                       stderr="Error BCP018: unexpected token")):
        result = validate_bicep(str(f))
    assert result.startswith("INVALID:")
    assert "BCP018" in result


def test_az_missing_returns_skipped(tmp_path):
    f = tmp_path / "main.bicep"
    f.write_text("ok\n")
    with patch("agent_harness.tools.bicep_tool.subprocess.run",
               side_effect=FileNotFoundError):
        result = validate_bicep(str(f))
    assert result.startswith("SKIPPED")
    assert "az" in result.lower()


def test_timeout_returns_invalid(tmp_path):
    f = tmp_path / "main.bicep"
    f.write_text("ok\n")
    with patch("agent_harness.tools.bicep_tool.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="az", timeout=30)):
        assert validate_bicep(str(f)) == "INVALID: timeout after 30s"


def test_file_not_found_on_disk(tmp_path):
    assert validate_bicep(str(tmp_path / "ghost.bicep")).startswith(
        "INVALID: file not found"
    )


def test_bicep_extension_missing_returns_skipped(tmp_path):
    f = tmp_path / "main.bicep"
    f.write_text("ok\n")
    with patch("agent_harness.tools.bicep_tool.subprocess.run",
               return_value=_fake_run(
                   returncode=1,
                   stderr="az : ERROR: The 'bicep' command is not installed.",
               )):
        result = validate_bicep(str(f))
    assert result.startswith("SKIPPED")
