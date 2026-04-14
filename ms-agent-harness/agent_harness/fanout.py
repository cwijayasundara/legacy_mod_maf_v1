"""Fan out an approved backlog to the migration pipeline, wave by wave."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from .discovery import paths as discovery_paths
from .discovery.artifacts import Backlog, BacklogItem, Stories
from .persistence.repository import MigrationRepository

logger = logging.getLogger("fanout")


@dataclass
class ModuleOutcome:
    module: str
    wave: int
    status: Literal["completed", "failed", "skipped"]
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

    run_id = repo.create_migrate_repo_run(repo_id)

    by_wave: dict[int, list[BacklogItem]] = defaultdict(list)
    for it in backlog.items:
        by_wave[it.wave].append(it)

    outcomes: dict[str, ModuleOutcome] = {}
    failed_story_ids: set[str] = set()
    skipped_because: dict[str, str] = {}

    for wave in sorted(by_wave):
        wave_items = by_wave[wave]

        async def _run(it: BacklogItem) -> ModuleOutcome:
            blocker = _first_blocked_dep(it, stories, failed_story_ids, skipped_because)
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

            if result.status == "completed":
                outcome = ModuleOutcome(module=it.module, wave=wave,
                                         status="completed",
                                         review_score=result.review_score)
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
            outcomes[it.work_item_id] = outcome
            if outcome.status == "failed":
                failed_story_ids.add(it.work_item_id)
            elif outcome.status == "skipped":
                skipped_because[it.work_item_id] = outcome.reason

    module_list = [outcomes[it.work_item_id] for it in backlog.items]
    all_completed = all(o.status == "completed" for o in module_list)
    any_completed = any(o.status == "completed" for o in module_list)
    status = "completed" if all_completed else ("partial" if any_completed else "failed")
    if not module_list:
        status = "completed"
    repo.complete_migrate_repo_run(run_id, status)
    return RepoMigrationResult(repo_id=repo_id, run_id=run_id,
                               status=status, modules=module_list)


def _first_blocked_dep(item: BacklogItem, stories: Stories,
                       failed: set[str], skipped: dict[str, str]) -> str | None:
    """Walk transitive depends_on; return the first failed/skipped ancestor id."""
    by_id = {s.id: s for s in stories.stories}
    stack = list(by_id[item.work_item_id].depends_on) if item.work_item_id in by_id else []
    seen: set[str] = set()
    while stack:
        dep = stack.pop()
        if dep in seen:
            continue
        seen.add(dep)
        if dep in failed or dep in skipped:
            return dep
        if dep in by_id:
            stack.extend(by_id[dep].depends_on)
    return None


class _noop_semaphore:
    """Async context manager that does nothing — used when no semaphore is supplied."""
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False
