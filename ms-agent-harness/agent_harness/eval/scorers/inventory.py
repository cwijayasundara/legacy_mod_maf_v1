"""Scanner-stage scorer — exact match on module IDs."""
from __future__ import annotations

from ...discovery.artifacts import Inventory
from .base import ScoreResult

THRESHOLD = 1.0


def score(got: Inventory, expected: Inventory) -> ScoreResult:
    got_ids = {m.id for m in got.modules}
    expected_ids = {m.id for m in expected.modules}
    missing = sorted(expected_ids - got_ids)
    extra = sorted(got_ids - expected_ids)

    if not expected_ids:
        s = 1.0 if not got_ids else 0.0
    else:
        s = len(got_ids & expected_ids) / len(expected_ids)
        if extra:
            s = min(s, 0.99)

    passed = not missing and not extra
    return ScoreResult(
        stage="inventory", score=s, passed=passed, threshold=THRESHOLD,
        details={"missing": missing, "extra": extra},
    )
