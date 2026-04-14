"""Workflow orchestration: hash → cache → 3-attempt self-heal → write artifact."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import ValidationError

from ..persistence.repository import MigrationRepository
from .artifacts import (
    Backlog, CriticReport, DependencyGraph, Inventory, Stories,
    ModuleBRD, SystemBRD, ModuleDesign, SystemDesign,
)
from . import paths


_SENTINEL = "__PARSE_ERROR__:"


def _parse_error_payload(exc: ValidationError) -> str:
    return _SENTINEL + json.dumps(exc.errors()[:10])


def _parse_error_report(result: str, schema_hint: str) -> CriticReport | None:
    if not result.startswith(_SENTINEL):
        return None
    errs = json.loads(result[len(_SENTINEL):])
    reasons = [f"{'/'.join(str(l) for l in e.get('loc', []))}: {e.get('msg', '')}" for e in errs]
    return CriticReport(
        verdict="FAIL",
        reasons=["LLM output failed schema validation"] + reasons,
        suggestions=[f"Re-emit JSON matching this schema exactly: {schema_hint}"],
    )

logger = logging.getLogger("discovery.workflow")

MAX_ATTEMPTS = 3
PROMPT_VERSION = "v1"

ProduceFn = Callable[[str], Awaitable[str]]
CriticFn = Callable[[str, dict], CriticReport]


def hash_inputs(repo_id: str, stage_name: str, parts: list[str],
                prompt_version: str = PROMPT_VERSION) -> str:
    h = hashlib.sha256()
    h.update(repo_id.encode())
    h.update(b"\0")
    h.update(stage_name.encode())
    h.update(b"\0")
    h.update(prompt_version.encode())
    for p in parts:
        h.update(b"\0")
        h.update(p.encode("utf-8", errors="replace"))
    return h.hexdigest()


async def run_stage(
    repo: MigrationRepository,
    repo_id: str,
    stage_name: str,
    produce: ProduceFn,
    critic: CriticFn,
    artifact_path: Path,
    input_hash: str,
    critic_context: dict | None = None,
) -> str:
    """Run one stage with caching + 3-attempt self-heal."""
    artifact_path = Path(artifact_path)
    if repo.stage_cache_hit(repo_id, stage_name, input_hash):
        cached = repo.get_cached_stage_path(repo_id, stage_name)
        if cached and Path(cached).exists():
            logger.info("[%s] cache hit %s", stage_name, cached)
            return Path(cached).read_text(encoding="utf-8")

    feedback = ""
    last: CriticReport | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info("[%s] attempt %d/%d", stage_name, attempt, MAX_ATTEMPTS)
        result = await produce(feedback)
        report = critic(result, critic_context or {})
        if report.verdict == "PASS":
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(result, encoding="utf-8")
            repo.cache_stage(repo_id, stage_name, input_hash, str(artifact_path))
            return result
        feedback = (
            "\n\n## Critic feedback (apply this):\n"
            + "\n".join(f"- {r}" for r in report.reasons)
            + ("\n\n### Suggestions\n" + "\n".join(f"- {s}" for s in report.suggestions)
               if report.suggestions else "")
        )
        last = report

    blocked = paths.blocked_path(repo_id, stage_name)
    blocked.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# Blocked: stage `{stage_name}`\n\n"
        f"Failed after {MAX_ATTEMPTS} self-heal attempts at "
        f"{datetime.now(timezone.utc).isoformat()}.\n\n"
        f"## Last critic report\n```json\n{last.model_dump_json(indent=2) if last else '{}'}\n```\n"
    )
    blocked.write_text(body, encoding="utf-8")
    raise RuntimeError(f"stage {stage_name} blocked after {MAX_ATTEMPTS} attempts")


async def run_discovery(repo_id: str, repo_path: str,
                        repo: MigrationRepository) -> dict:
    """Run the 5 LLM stages. Returns dict with status + artifact paths."""
    from . import repo_scanner, dependency_grapher, brd_extractor
    from . import architect, story_decomposer
    from .critics.graph_critic import critique_graph
    from .critics.brd_critic import critique_brds
    from .critics.design_critic import critique_designs
    from .critics.story_critic import critique_stories

    repo.create_discovery_run(repo_id)
    root = Path(repo_path).resolve()

    # Stage 1: scanner
    inv_hash = hash_inputs(repo_id, "scanner", [str(root)])

    async def _produce_scanner(feedback: str) -> str:
        try:
            inv = await repo_scanner.scan_repo(repo_id, str(root), extra_instructions=feedback)
            return inv.model_dump_json()
        except ValidationError as exc:
            return _parse_error_payload(exc)

    def _critic_scanner(result: str, ctx: dict) -> CriticReport:
        bad = _parse_error_report(result, schema_hint=(
            "{repo_meta: {root_path, total_files, total_loc, discovered_at}, "
            "modules: [{id, path, language, handler_entrypoint, loc, config_files}]}"
        ))
        if bad:
            return bad
        inv = Inventory.model_validate_json(result)
        return repo_scanner.sanity_check(inv, repo_root=root)

    raw_inv = await run_stage(repo, repo_id, "scanner", _produce_scanner, _critic_scanner,
                              paths.inventory_path(repo_id), inv_hash)
    inventory = Inventory.model_validate_json(raw_inv)

    # Stage 2: grapher
    g_hash = hash_inputs(repo_id, "grapher", [raw_inv])

    async def _produce_grapher(feedback: str) -> str:
        try:
            g = await dependency_grapher.build_graph(repo_id, root, inventory,
                                                     extra_instructions=feedback)
            return g.model_dump_json()
        except ValidationError as exc:
            return _parse_error_payload(exc)

    def _critic_grapher(result: str, ctx: dict) -> CriticReport:
        bad = _parse_error_report(result,
            schema_hint="{nodes:[{id,kind,attrs}], edges:[{src,dst,kind}]}")
        if bad:
            return bad
        g = DependencyGraph.model_validate_json(result)
        return critique_graph(g, root, inventory)

    raw_graph = await run_stage(repo, repo_id, "grapher", _produce_grapher, _critic_grapher,
                                paths.graph_path(repo_id), g_hash)
    graph = DependencyGraph.model_validate_json(raw_graph)

    # Stage 3: brd
    b_hash = hash_inputs(repo_id, "brd", [raw_inv, raw_graph])
    cached_brds: list[ModuleBRD] = []
    cached_sys: SystemBRD | None = None

    async def _produce_brd(feedback: str) -> str:
        nonlocal cached_brds, cached_sys
        cached_brds, cached_sys = await brd_extractor.extract_brds(
            repo_id, root, inventory, graph, extra_instructions=feedback,
        )
        return json.dumps({"modules": [b.model_dump() for b in cached_brds],
                           "system": cached_sys.model_dump()})

    def _critic_brd(result: str, ctx: dict) -> CriticReport:
        return critique_brds(cached_brds, cached_sys, inventory, graph)

    await run_stage(repo, repo_id, "brd", _produce_brd, _critic_brd,
                    paths.brd_dir(repo_id) / "_summary.json", b_hash)

    # Stage 4: architect
    d_hash = hash_inputs(repo_id, "architect", [raw_inv, raw_graph,
                          json.dumps([b.model_dump() for b in cached_brds])])
    cached_designs: list[ModuleDesign] = []
    cached_sys_design: SystemDesign | None = None

    async def _produce_design(feedback: str) -> str:
        nonlocal cached_designs, cached_sys_design
        cached_designs, cached_sys_design = await architect.design(
            repo_id, inventory, graph, cached_brds, cached_sys,
            extra_instructions=feedback,
        )
        return json.dumps({"modules": [d.model_dump() for d in cached_designs],
                           "system": cached_sys_design.model_dump()})

    def _critic_design(result: str, ctx: dict) -> CriticReport:
        return critique_designs(cached_designs, cached_sys_design,
                                inventory, graph, cached_brds)

    await run_stage(repo, repo_id, "architect", _produce_design, _critic_design,
                    paths.design_dir(repo_id) / "_summary.json", d_hash)

    # Stage 5: stories
    s_hash = hash_inputs(repo_id, "stories", [raw_inv, raw_graph,
                          json.dumps([b.model_dump() for b in cached_brds]),
                          json.dumps([d.model_dump() for d in cached_designs])])

    async def _produce_stories(feedback: str) -> str:
        try:
            s = await story_decomposer.decompose(
                repo_id, inventory, graph, cached_brds, cached_sys,
                cached_designs, cached_sys_design, extra_instructions=feedback,
            )
            return s.model_dump_json()
        except ValidationError as exc:
            return _parse_error_payload(exc)

    def _critic_stories(result: str, ctx: dict) -> CriticReport:
        bad = _parse_error_report(result,
            schema_hint="{epics:[{id,module_id,title,story_ids}], stories:[{id,epic_id,title,description,acceptance_criteria:[{text}],depends_on,blocks,estimate}]}")
        if bad:
            return bad
        s = Stories.model_validate_json(result)
        return critique_stories(s, inventory)

    await run_stage(repo, repo_id, "stories", _produce_stories, _critic_stories,
                    paths.stories_path(repo_id), s_hash)

    return {
        "status": "ok",
        "stages": ["scanner", "grapher", "brd", "architect", "stories"],
        "artifacts": {
            "inventory": str(paths.inventory_path(repo_id)),
            "graph": str(paths.graph_path(repo_id)),
            "brd_dir": str(paths.brd_dir(repo_id)),
            "design_dir": str(paths.design_dir(repo_id)),
            "stories": str(paths.stories_path(repo_id)),
        },
    }


async def run_planning(repo_id: str, repo: MigrationRepository) -> Backlog:
    """Run the deterministic WaveScheduler over stored artifacts."""
    from .wave_scheduler import schedule

    inv_path = paths.inventory_path(repo_id)
    graph_path = paths.graph_path(repo_id)
    stories_path = paths.stories_path(repo_id)
    for p in (inv_path, graph_path, stories_path):
        if not p.exists():
            raise FileNotFoundError(f"missing artifact: {p}")

    inventory = Inventory.model_validate_json(inv_path.read_text())
    graph = DependencyGraph.model_validate_json(graph_path.read_text())
    stories = Stories.model_validate_json(stories_path.read_text())
    lang_by_module = {m.id: m.language for m in inventory.modules}
    backlog = schedule(stories, language_by_module=lang_by_module,
                       inventory=inventory, graph=graph)

    out = paths.backlog_path(repo_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(backlog.model_dump_json(indent=2), encoding="utf-8")
    return backlog
