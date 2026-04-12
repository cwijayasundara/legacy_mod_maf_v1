"""
File tools — read, write, search, list operations.

Registered as @tool functions that agents can call during migration.
"""

import os
import re
import subprocess
from pathlib import Path

from agent_framework import tool


@tool(approval_mode="never_require")
def read_file(path: str) -> str:
    """Read the contents of a file. Returns the full text content."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return f"ERROR: File not found: {path}"
    except Exception as e:
        return f"ERROR reading {path}: {e}"


@tool(approval_mode="never_require")
def write_file(path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"ERROR writing {path}: {e}"


@tool(approval_mode="never_require")
def search_files(pattern: str, directory: str = ".", file_glob: str = "") -> str:
    """
    Search for a regex pattern in files. Returns matching lines with file:line format.
    Optionally filter by file glob (e.g., '*.py', '*.js').
    Uses ripgrep if available, falls back to Python re.
    """
    try:
        cmd = ["rg", "--no-heading", "-n", pattern]
        if file_glob:
            cmd.extend(["--glob", file_glob])
        cmd.append(directory)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            # Limit output to prevent token explosion
            lines = result.stdout.strip().split("\n")
            if len(lines) > 50:
                return "\n".join(lines[:50]) + f"\n... ({len(lines) - 50} more matches)"
            return result.stdout.strip()
        return f"No matches for '{pattern}' in {directory}"
    except FileNotFoundError:
        # ripgrep not installed — fall back to Python
        return _python_search(pattern, directory, file_glob)
    except Exception as e:
        return f"ERROR searching: {e}"


@tool(approval_mode="never_require")
def list_directory(path: str = ".", recursive: bool = False) -> str:
    """List files in a directory. Set recursive=True for tree view."""
    try:
        p = Path(path)
        if not p.is_dir():
            return f"ERROR: Not a directory: {path}"

        if recursive:
            files = sorted(str(f.relative_to(p)) for f in p.rglob("*") if f.is_file())
        else:
            files = sorted(str(f.relative_to(p)) for f in p.iterdir())

        if len(files) > 100:
            return "\n".join(files[:100]) + f"\n... ({len(files) - 100} more files)"
        return "\n".join(files) if files else "(empty directory)"
    except Exception as e:
        return f"ERROR listing {path}: {e}"


def _python_search(pattern: str, directory: str, file_glob: str) -> str:
    """Fallback search using Python re module."""
    results = []
    p = Path(directory)
    glob_pattern = file_glob or "**/*"
    regex = re.compile(pattern)

    for filepath in p.glob(glob_pattern):
        if not filepath.is_file():
            continue
        try:
            for i, line in enumerate(filepath.read_text(errors="replace").split("\n"), 1):
                if regex.search(line):
                    results.append(f"{filepath}:{i}:{line.strip()}")
                    if len(results) >= 50:
                        return "\n".join(results) + "\n... (truncated at 50 matches)"
        except Exception:
            continue

    return "\n".join(results) if results else f"No matches for '{pattern}'"
