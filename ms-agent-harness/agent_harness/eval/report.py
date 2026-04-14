"""Aggregate ScoreResults into a run directory with JSON + markdown."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from .scorers.base import ScoreResult


@dataclass
class ReportBundle:
    corpus: str
    tier: str
    overall_passed: bool
    per_stage: dict[str, ScoreResult]
    run_dir: Path


def render(results: list[ScoreResult], corpus_name: str, tier: str,
           out_dir: Path) -> ReportBundle:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(out_dir) / f"{timestamp}-{corpus_name}"
    run_dir.mkdir(parents=True, exist_ok=True)

    overall_passed = all(r.passed for r in results)
    per_stage = {r.stage: r for r in results}

    payload = {
        "corpus": corpus_name,
        "tier": tier,
        "overall_passed": overall_passed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": [asdict(r) for r in results],
    }
    (run_dir / "report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    verdict = "PASS" if overall_passed else "FAIL"
    lines = [
        f"# Eval report: {corpus_name} ({tier}) — {verdict}",
        "",
        "| Stage | Score | Threshold | Passed |",
        "|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.stage} | {r.score:.3f} | {r.threshold:.3f} | "
            f"{'PASS' if r.passed else 'FAIL'} |"
        )
    lines.append("")
    for r in results:
        lines.append(f"## {r.stage}")
        lines.append("```json")
        lines.append(json.dumps(r.details, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
    (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

    return ReportBundle(
        corpus=corpus_name, tier=tier, overall_passed=overall_passed,
        per_stage=per_stage, run_dir=run_dir,
    )
