"""Validate a Bicep file by transpiling with the Azure CLI."""
from __future__ import annotations

import subprocess
from pathlib import Path

from agent_framework import tool


@tool(approval_mode="never_require")
def validate_bicep(path: str) -> str:
    """Transpile <path> with `az bicep build --stdout`.

    Returns 'VALID', 'INVALID: <stderr>', or 'SKIPPED: <reason>'.
    Timeout: 30s.
    """
    p = Path(path)
    if not p.is_file():
        return f"INVALID: file not found: {path}"
    try:
        result = subprocess.run(
            ["az", "bicep", "build", "--stdout", "--file", str(p)],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return "SKIPPED: az CLI not installed"
    except subprocess.TimeoutExpired:
        return "INVALID: timeout after 30s"

    if result.returncode == 0:
        return "VALID"
    stderr = (result.stderr or "").strip()[:2000]
    low = stderr.lower()
    if "bicep' command is not installed" in stderr or "bicep extension" in low:
        return f"SKIPPED: bicep extension not available: {stderr}"
    return f"INVALID: {stderr}"
