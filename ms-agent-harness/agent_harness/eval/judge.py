"""LLM-as-judge helper for rubric-based scoring."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel

from ..base import create_agent, run_with_retry

logger = logging.getLogger("eval.judge")

RUBRICS_DIR = Path(__file__).parent / "rubrics"


@dataclass
class Criterion:
    name: str
    weight: float
    description: str


@dataclass
class Rubric:
    name: str
    description: str
    judge_model: str
    temperature: float
    criteria: list[Criterion] = field(default_factory=list)


class _JudgeCriterion(BaseModel):
    name: str
    score: float
    reasoning: str = ""


class _JudgeResponse(BaseModel):
    criteria: list[_JudgeCriterion]
    overall: float


@dataclass
class JudgeScore:
    raw_overall: float
    normalised: float
    per_criterion: dict[str, float]
    reasoning: dict[str, str]


def load_rubric(name: str) -> Rubric:
    path = RUBRICS_DIR / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Rubric(
        name=data["name"],
        description=data.get("description", ""),
        judge_model=data.get("judge_model", "gpt-5.4-mini"),
        temperature=float(data.get("temperature", 0.0)),
        criteria=[Criterion(**c) for c in data.get("criteria", [])],
    )


async def _run_judge(model: str, messages: str, temperature: float) -> str:
    """Indirection point so tests can patch a single seam."""
    agent = create_agent(role="eval_judge", tools=[])
    return await run_with_retry(agent, messages)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


@dataclass
class Judge:
    async def score(self, rubric: Rubric, artifact: str,
                    context: dict) -> JudgeScore:
        prompt = _format_prompt(rubric, artifact, context)
        raw = await _run_judge(rubric.judge_model, prompt, rubric.temperature)
        try:
            parsed = _JudgeResponse.model_validate_json(_strip_fences(raw))
        except Exception as exc:
            raise ValueError(f"could not parse judge response: {exc}") from exc

        per_criterion = {c.name: c.score for c in parsed.criteria}
        reasoning = {c.name: c.reasoning for c in parsed.criteria}
        normalised = _weighted_normalised(parsed, rubric)
        return JudgeScore(raw_overall=parsed.overall, normalised=normalised,
                          per_criterion=per_criterion, reasoning=reasoning)


def _format_prompt(rubric: Rubric, artifact: str, context: dict) -> str:
    ctx_block = "\n".join(f"- {k}: {v}" for k, v in context.items())
    criteria_block = "\n".join(
        f"- {c.name} (weight {c.weight}): {c.description}" for c in rubric.criteria
    )
    return (
        "You are a rubric-based evaluator. Score the ARTIFACT against each CRITERION "
        "on a 0-10 scale. Return ONLY JSON (no prose, no fences):\n\n"
        '{"criteria": [{"name": "...", "score": 0-10, "reasoning": "..."}], '
        '"overall": <weighted mean, 0-10>}\n\n'
        f"RUBRIC: {rubric.name} - {rubric.description}\n"
        f"CRITERIA:\n{criteria_block}\n\n"
        f"CONTEXT:\n{ctx_block}\n\n"
        f"ARTIFACT:\n{artifact}\n"
    )


def _weighted_normalised(parsed: _JudgeResponse, rubric: Rubric) -> float:
    by_name = {c.name: c for c in parsed.criteria}
    total = 0.0
    used_weight = 0.0
    for c in rubric.criteria:
        if c.name in by_name:
            total += by_name[c.name].score * c.weight
            used_weight += c.weight
    if used_weight == 0:
        return 0.0
    return max(0.0, min(1.0, total / (10.0 * used_weight)))
