"""Shared dataclass for scorer output."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScoreResult:
    stage: str
    score: float
    passed: bool
    threshold: float
    details: dict[str, Any] = field(default_factory=dict)
