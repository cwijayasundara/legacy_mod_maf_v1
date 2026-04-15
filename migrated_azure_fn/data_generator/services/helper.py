from __future__ import annotations

from typing import Any


def remove_trailing_spaces(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: remove_trailing_spaces(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [remove_trailing_spaces(v) for v in obj]
    if isinstance(obj, str):
        return obj.strip()
    return obj
