"""Fan out an approved backlog to the migration pipeline, wave by wave."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from . import paths as _artifact_paths
from .discovery import paths as discovery_paths
from .discovery.artifacts import Backlog, BacklogItem, Stories
from .persistence.repository import MigrationRepository

logger = logging.getLogger("fanout")


# Any of these filenames, anywhere under MIGRATED_DIR/<module>/, counts as
# "the coder produced output" — enough for downstream stories to proceed.
_CODE_MARKERS = (
    "function_app.py", "index.js", "index.ts", "Function.java", "Function.cs",
)


def _has_generated_code(module: str) -> bool:
    module_dir = _artifact_paths.migrated_dir(module)
    if not module_dir.is_dir():
        return False
    for marker in _CODE_MARKERS:
        if any(module_dir.rglob(marker)):
            return True
    return False


@dataclass
class ModuleOutcome:
    module: str
    wave: int
    status: Literal["completed", "completed_with_warnings", "failed", "skipped"]
    reason: str = ""
    review_score: int | None = None


@dataclass
class RepoMigrationResult:
    repo_id: str
    run_id: int
    status: Literal["completed", "partial", "failed"]
    modules: list[ModuleOutcome] = field(default_factory=list)


async def migrate_repo(
    repo_id: str,
    repo: MigrationRepository,
    pipeline,
    semaphore: asyncio.Semaphore | None = None,
) -> RepoMigrationResult:
    """Fan out an approved backlog to pipeline.run, wave by wave.

    Concurrent within a wave, continue-on-error. Descendants of failed
    modules (via stories.json depends_on) are marked skipped.
    """
    if not repo.is_backlog_approved(repo_id):
        raise PermissionError(
            f"backlog for {repo_id} is not approved; call /approve/backlog/{repo_id}"
        )

    backlog_path = discovery_paths.backlog_path(repo_id)
    stories_path = discovery_paths.stories_path(repo_id)
    if not backlog_path.exists():
        raise FileNotFoundError(f"backlog missing: {backlog_path}")
    if not stories_path.exists():
        raise FileNotFoundError(f"stories missing: {stories_path}")

    backlog = Backlog.model_validate_json(backlog_path.read_text())
    stories = Stories.model_validate_json(stories_path.read_text())
    backlog, module_deps = _collapse_backlog_to_modules(backlog, stories)

    run_id = repo.create_migrate_repo_run(repo_id)

    by_wave: dict[int, list[BacklogItem]] = defaultdict(list)
    for it in backlog.items:
        by_wave[it.wave].append(it)

    outcomes: dict[str, ModuleOutcome] = {}
    failed_modules: set[str] = set()
    skipped_because: dict[str, str] = {}

    for wave in sorted(by_wave):
        wave_items = by_wave[wave]
        wave_started = time.perf_counter()
        logger.info("[fanout] wave %d starting with modules=%s", wave, [it.module for it in wave_items])

        async def _run(it: BacklogItem) -> ModuleOutcome:
            blocker = _first_blocked_dep(it.module, module_deps, failed_modules, skipped_because)
            if blocker:
                outcome = ModuleOutcome(
                    module=it.module, wave=wave,
                    status="skipped", reason=f"{blocker} failed or skipped",
                )
                repo.record_migrate_module(run_id, it.module, wave,
                                            status="skipped", reason=outcome.reason)
                return outcome

            repo.record_migrate_module(run_id, it.module, wave, status="running")
            sem = semaphore or _noop_semaphore()
            try:
                async with sem:
                    result = await pipeline.run(
                        module=it.module, language=it.language,
                        work_item_id=it.work_item_id, title=it.title,
                        description=it.description,
                        acceptance_criteria=it.acceptance_criteria,
                        source_paths=it.source_paths,
                        context_paths=it.context_paths,
                    )
            except Exception as exc:
                logger.exception("pipeline crashed on %s", it.module)
                outcome = ModuleOutcome(module=it.module, wave=wave,
                                         status="failed",
                                         reason=f"exception: {exc!r}")
                repo.record_migrate_module(run_id, it.module, wave,
                                            status="failed",
                                            reason=outcome.reason)
                return outcome

            # Phase policy: code generation is the goal, downstream CI gates
            # quality. We map by what actually landed on disk:
            #   - reviewer APPROVED        -> "completed"
            #   - any other outcome + code on disk (function_app.py / equiv.)
            #     -> "completed_with_warnings" (soft-pass; downstream proceeds)
            #   - no code on disk          -> "failed" (hard; downstream skips)
            code_generated = _has_generated_code(it.module)
            if result.status == "completed":
                outcome = ModuleOutcome(module=it.module, wave=wave,
                                         status="completed",
                                         review_score=result.review_score)
            elif code_generated:
                outcome = ModuleOutcome(
                    module=it.module, wave=wave,
                    status="completed_with_warnings",
                    review_score=result.review_score,
                    reason=result.message or result.status,
                )
            else:
                outcome = ModuleOutcome(module=it.module, wave=wave,
                                         status="failed",
                                         reason=result.message or result.status)
            repo.record_migrate_module(
                run_id, it.module, wave,
                status=outcome.status, reason=outcome.reason,
                review_score=outcome.review_score,
            )
            return outcome

        results = await asyncio.gather(*(_run(it) for it in wave_items))
        for it, outcome in zip(wave_items, results):
            outcomes[it.module] = outcome
            if outcome.status == "failed":
                failed_modules.add(it.module)
            elif outcome.status == "skipped":
                skipped_because[it.module] = outcome.reason
        logger.info("[fanout] wave %d complete in %.2fs", wave, time.perf_counter() - wave_started)

    module_list = [outcomes[it.module] for it in backlog.items]
    _ok = {"completed", "completed_with_warnings"}
    all_completed = all(o.status in _ok for o in module_list)
    any_completed = any(o.status in _ok for o in module_list)
    status = "completed" if all_completed else ("partial" if any_completed else "failed")
    if not module_list:
        status = "completed"
    repo.complete_migrate_repo_run(run_id, status)
    return RepoMigrationResult(repo_id=repo_id, run_id=run_id,
                               status=status, modules=module_list)


def _first_blocked_dep(module: str, module_deps: dict[str, set[str]],
                       failed: set[str], skipped: dict[str, str]) -> str | None:
    """Walk transitive module dependencies; return the first failed/skipped ancestor."""
    stack = list(module_deps.get(module, set()))
    seen: set[str] = set()
    while stack:
        dep = stack.pop()
        if dep in seen:
            continue
        seen.add(dep)
        if dep in failed or dep in skipped:
            return dep
        stack.extend(module_deps.get(dep, set()))
    return None


def _collapse_backlog_to_modules(backlog: Backlog, stories: Stories) -> tuple[Backlog, dict[str, set[str]]]:
    epic_module = {epic.id: epic.module_id for epic in stories.epics}
    story_module = {story.id: epic_module.get(story.epic_id, story.epic_id) for story in stories.stories}
    module_deps: dict[str, set[str]] = defaultdict(set)
    module_order: list[str] = []
    grouped: dict[str, list[BacklogItem]] = defaultdict(list)

    for item in backlog.items:
        if item.module not in grouped:
            module_order.append(item.module)
        grouped[item.module].append(item)

    for story in stories.stories:
        mod = story_module.get(story.id)
        if mod is None:
            continue
        for dep in story.depends_on:
            dep_mod = story_module.get(dep)
            if dep_mod and dep_mod != mod:
                module_deps[mod].add(dep_mod)

    if len(grouped) == len(backlog.items):
        return backlog, module_deps

    logger.info(
        "[fanout] collapsing backlog from %d story items to %d module items",
        len(backlog.items),
        len(grouped),
    )

    merged_items: list[BacklogItem] = []
    compacted_waves = _compact_module_waves(module_order, module_deps)
    for module in module_order:
        items = grouped[module]
        first = items[0]
        merged_items.append(
            BacklogItem(
                module=module,
                language=first.language,
                work_item_id=first.work_item_id,
                title=first.title or module,
                description=_merge_text_fields(item.description for item in items),
                acceptance_criteria=_merge_text_fields(item.acceptance_criteria for item in items),
                source_paths=_merge_lists(item.source_paths for item in items),
                context_paths=_merge_lists(item.context_paths for item in items),
                wave=compacted_waves[module],
            )
        )
    merged_items.sort(key=lambda item: (item.wave, module_order.index(item.module)))
    return Backlog(items=merged_items), module_deps


def _compact_module_waves(module_order: list[str], module_deps: dict[str, set[str]]) -> dict[str, int]:
    wave_of: dict[str, int] = {}
    remaining = set(module_order)
    while remaining:
        progressed = False
        for module in module_order:
            if module not in remaining:
                continue
            deps = module_deps.get(module, set())
            if not deps.issubset(wave_of):
                continue
            wave_of[module] = max((wave_of[d] for d in deps), default=0) + 1
            remaining.remove(module)
            progressed = True
        if not progressed:
            # Fall back to a conservative single trailing wave for any cycle-like mess.
            fallback = max(wave_of.values(), default=0) + 1
            for module in list(remaining):
                wave_of[module] = fallback
                remaining.remove(module)
    return wave_of


def _merge_lists(groups) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item not in seen:
                seen.add(item)
                merged.append(item)
    return merged


def _merge_text_fields(values) -> str:
    seen: set[str] = set()
    chunks: list[str] = []
    for value in values:
        text = (value or "").strip()
        if text and text not in seen:
            seen.add(text)
            chunks.append(text)
    return "\n\n".join(chunks)


class _noop_semaphore:
    """Async context manager that does nothing — used when no semaphore is supplied."""
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False
