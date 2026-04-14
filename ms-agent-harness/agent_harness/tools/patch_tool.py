"""Search-replace editing tool. All-or-nothing batch semantics."""
from __future__ import annotations

from pathlib import Path

from agent_framework import tool


@tool(approval_mode="never_require")
def apply_patch(edits: list[dict]) -> str:
    """Apply a batch of search-replace edits atomically.

    Each edit is a dict: {file, old_string, new_string, expected_count}.
    expected_count defaults to 1. All edits are validated before any file
    is touched; any failure aborts the entire batch and no file is modified.

    Returns a summary string. On failure, returns 'ERROR: <reason>'.
    """
    # Per-file working content, edits applied sequentially against it.
    working: dict[Path, str] = {}
    plans: list[tuple[Path, str, str, int]] = []
    for i, edit in enumerate(edits):
        try:
            file = edit["file"]
            old = edit["old_string"]
            new = edit["new_string"]
            expected = int(edit.get("expected_count", 1))
        except (KeyError, TypeError, ValueError) as exc:
            return f"ERROR: edit {i} malformed: {exc}"
        path = Path(file)
        if path not in working:
            if not path.is_file():
                return f"ERROR: edit {i}: file not found: {file}"
            try:
                working[path] = path.read_text(encoding="utf-8")
            except OSError as exc:
                return f"ERROR: edit {i}: could not read {file}: {exc}"
        content = working[path]
        count = content.count(old)
        if count != expected:
            return (f"ERROR: edit {i} for {file}: "
                    f"expected {expected} match(es) of old_string, found {count}")
        working[path] = content.replace(old, new, expected)
        plans.append((path, old, new, expected))

    for path, updated in working.items():
        path.write_text(updated, encoding="utf-8")

    return f"applied {len(edits)} edit(s) to {len(working)} file(s)"
