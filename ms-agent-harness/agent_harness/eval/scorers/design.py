"""Design-stage scorer — structural + LLM-as-judge."""
from __future__ import annotations

import re
from typing import Any

from ...discovery.artifacts import DependencyGraph, Inventory
from ..judge import Judge, JudgeScore, load_rubric
from .base import ScoreResult

THRESHOLD = 0.7
REQUIRED_SECTIONS = (
    "Function Plan", "Trigger Bindings", "State Mapping",
    "Secrets", "Identity", "IaC", "Observability",
)


async def _judge_score(rubric, artifact: str, context: dict) -> JudgeScore:
    judge = Judge()
    return await judge.score(rubric, artifact, context)


async def score(design: dict[str, str], inventory: Inventory,
                graph: DependencyGraph) -> ScoreResult:
    rubric = load_rubric("design")

    missing_module_designs = sorted(
        [m.id for m in inventory.modules if m.id not in design]
    )
    structural_per_module: dict[str, Any] = {}
    structural_scores: list[float] = []
    for module_id, body in design.items():
        missing = [sec for sec in REQUIRED_SECTIONS if not _section_has_content(body, sec)]
        per = 1.0 - (len(missing) / len(REQUIRED_SECTIONS))
        structural_per_module[module_id] = {"missing_sections": missing, "score": per}
        structural_scores.append(per)
    if missing_module_designs:
        structural_scores.extend([0.0] * len(missing_module_designs))
    structural_score = (sum(structural_scores) / len(structural_scores)) \
        if structural_scores else 0.0

    judge_scores: list[float] = []
    judge_details: dict[str, Any] = {}
    for module_id, body in design.items():
        edges = [f"{e.src} -[{e.kind}]-> {e.dst}" for e in graph.edges
                 if e.src == module_id or e.dst == module_id]
        js = await _judge_score(
            rubric, artifact=body,
            context={"module_id": module_id, "edges": "; ".join(edges)},
        )
        judge_scores.append(js.normalised)
        judge_details[module_id] = {"raw_overall": js.raw_overall,
                                    "per_criterion": js.per_criterion,
                                    "reasoning": js.reasoning}
    judge_score = (sum(judge_scores) / len(judge_scores)) if judge_scores else 0.0

    total = (structural_score + judge_score) / 2
    passed = total >= THRESHOLD and not missing_module_designs

    return ScoreResult(
        stage="design", score=total, passed=passed, threshold=THRESHOLD,
        details={
            "structural": structural_per_module,
            "structural_score": structural_score,
            "missing_module_designs": missing_module_designs,
            "judge_score": judge_score,
            "judge": judge_details,
        },
    )


def _section_text(body: str, name: str) -> str:
    pattern = rf"^##\s+{re.escape(name)}\b.*?$(.*?)(?=^##\s|\Z)"
    m = re.search(pattern, body, flags=re.MULTILINE | re.DOTALL)
    return (m.group(1) if m else "").strip()


def _section_has_content(body: str, name: str) -> bool:
    text = _section_text(body, name)
    for line in text.splitlines():
        line = line.strip()
        if line and line != "- " and not line.startswith("#"):
            return True
    return False
