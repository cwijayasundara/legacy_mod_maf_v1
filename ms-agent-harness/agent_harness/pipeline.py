"""
Migration pipeline orchestrator.

Runs the 4-agent sequential pipeline: analyzer → coder → tester → reviewer
with self-healing loops, sprint contract negotiation, state management,
ratcheting enforcement, and checkpoint/resume via SQLite.

This is the core engine — called by the REST API or CLI.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import observability
from .analyzer import analyze_module
from .coder import propose_contract, migrate_module
from .tester import finalize_contract, evaluate_module
from .reviewer import review_module
from .security_reviewer import security_review
from .config import load_settings
from .persistence.repository import MigrationRepository
from .persistence.state_manager import StateManager
from .quality.architecture_checker import check_architecture
from .quality.code_quality import check_directory

logger = logging.getLogger("pipeline")


class _StageTimeout(RuntimeError):
    def __init__(self, role: str, seconds: float):
        super().__init__(f"{role} timed out after {seconds}s")
        self.role = role
        self.seconds = seconds


async def _with_stage_timeout(settings, role: str, coro):
    try:
        return await asyncio.wait_for(coro, timeout=settings.timeout_for(role))
    except asyncio.TimeoutError:
        raise _StageTimeout(role, settings.timeout_for(role))


def _common_ancestor(paths: list[Path]) -> Path:
    """Return the deepest directory that is an ancestor of every path.

    Falls back to `Path('/')` in the pathological case of paths from
    different roots.
    """
    resolved = [p.resolve() for p in paths if p]
    if not resolved:
        return Path("/")
    if len(resolved) == 1:
        return resolved[0].parent if resolved[0].is_file() else resolved[0]
    ancestors = set(resolved[0].parents) | {resolved[0] if resolved[0].is_dir() else resolved[0].parent}
    for p in resolved[1:]:
        pp = set(p.parents) | {p if p.is_dir() else p.parent}
        ancestors &= pp
    if not ancestors:
        return Path("/")
    return max(ancestors, key=lambda x: len(x.parts))


@dataclass
class PipelineResult:
    """Result of a migration pipeline run."""
    module: str
    status: str  # completed, blocked, failed
    message: str = ""
    review_score: int | None = None
    coverage: float | None = None
    gates_passed: list[int] = None
    gates_failed: list[int] = None

    def __post_init__(self):
        self.gates_passed = self.gates_passed or []
        self.gates_failed = self.gates_failed or []


class MigrationPipeline:
    """
    Sequential migration pipeline with self-healing.

    Flow:
    1. Read persistent context (learned rules, progress, program.md)
    2. Analyzer: dependency analysis + complexity scoring
    3. Sprint contract: coder proposes, tester finalizes
    4. Self-healing loop (up to 3 attempts):
       a. Coder: TDD migration
       b. Tester: 3-layer evaluation
       c. If FAIL: tester writes structured failure report → coder retries
    5. Reviewer: 8-point quality gate
    6. Update state (progress, learned rules, coverage baseline)
    """

    def __init__(self, project_root: str = ""):
        self.project_root = project_root or str(Path(__file__).parent.parent)
        self.settings = load_settings()
        # Scope the SQLite DB to the project root so multiple workspaces
        # (e.g. worktrees, test tmpdirs) do not collide on cached analysis.
        self.repo = MigrationRepository(
            db_path=str(Path(self.project_root) / "migration.db")
        )
        self.state = StateManager()

    async def initialize(self):
        """Initialize persistence layers."""
        self.repo.initialize()
        await self.state.initialize()

    async def run(
        self,
        module: str,
        language: str,
        work_item_id: str = "LOCAL",
        title: str = "",
        description: str = "",
        acceptance_criteria: str = "",
        source_paths: list[str] | tuple = (),
        context_paths: list[str] | tuple = (),
    ) -> PipelineResult:
        """
        Run the full migration pipeline for a single module.
        """
        await self.initialize()
        await self.state.pull_state()

        source_paths = list(source_paths) if source_paths else []
        context_paths = list(context_paths) if context_paths else []

        logger.info("Pipeline starting: %s (%s)", module, language)
        run_id = self.repo.start_run(module, language, work_item_id)

        # Derive repo_root + module_path for AGENTS.md injection (sub-project D.1).
        if source_paths:
            module_path = str(Path(source_paths[0]).resolve().parent)
            all_paths = [Path(p) for p in list(source_paths) + list(context_paths)]
            repo_root = str(_common_ancestor(all_paths))
        else:
            module_path = os.path.join(self.project_root, "src", "lambda", module)
            repo_root = self.project_root

        source_dir = os.path.join(self.project_root, "src", "lambda", module)
        output_dir = os.path.join(self.project_root, "migration-analysis", module)
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(self.project_root, "src", "azure-functions", module), exist_ok=True)
        os.makedirs(os.path.join(self.project_root, "infrastructure", module), exist_ok=True)

        gates_passed = []
        gates_failed = []

        try:
            # ─── Gate 1: Analysis ──────────────────────────────────────
            observability.set_stage("analyzer", attempt=1)
            logger.info("[Gate 1] Running analyzer for %s", module)
            cached = self.repo.get_cached_analysis(module)
            if cached:
                logger.info("Using cached analysis for %s", module)
                analysis = cached.get("analysis_text", "")
            else:
                try:
                    analysis = await _with_stage_timeout(
                        self.settings, "analyzer",
                        analyze_module(
                            module=module, language=language, source_dir=source_dir,
                            source_paths=source_paths, context_paths=context_paths,
                            repo_root=repo_root, module_path=module_path,
                        ),
                    )
                except _StageTimeout as exc:
                    self.repo.complete_run(run_id, "blocked", str(exc))
                    await self.state.push_state()
                    return PipelineResult(
                        module=module, status="blocked", message=str(exc),
                        gates_failed=[1],
                    )
                self.repo.cache_analysis(
                    module,
                    {"analysis_text": analysis},
                    score=0, level="UNKNOWN",
                )
            gates_passed.append(1)

            # ─── Gate 2: Sprint Contract Negotiation ───────────────────
            logger.info("[Contract] Coder proposing sprint contract for %s", module)
            contract = await propose_contract(module, language, analysis, acceptance_criteria)

            logger.info("[Contract] Tester finalizing sprint contract for %s", module)
            contract = await finalize_contract(module, contract)
            gates_passed.append(2)

            # ─── Gates 3-5: Self-Healing Migration Loop ────────────────
            max_attempts = self.settings.quality.max_self_healing_attempts
            migration_passed = False

            for attempt in range(1, max_attempts + 1):
                logger.info("[Gate 3] Migration attempt %d/%d for %s", attempt, max_attempts, module)

                # Coder migrates
                observability.set_stage("coder", attempt=attempt)
                try:
                    await _with_stage_timeout(
                        self.settings, "coder",
                        migrate_module(
                            module=module, language=language, source_dir=source_dir,
                            analysis_path=analysis, attempt=attempt,
                            source_paths=source_paths, context_paths=context_paths,
                            repo_root=repo_root, module_path=module_path,
                        ),
                    )
                except _StageTimeout as exc:
                    self.repo.complete_run(run_id, "blocked", str(exc))
                    await self.state.push_state()
                    return PipelineResult(
                        module=module, status="blocked", message=str(exc),
                        gates_failed=[3],
                    )
                gates_passed.append(3) if 3 not in gates_passed else None

                # Tester evaluates
                observability.set_stage("tester", attempt=attempt)
                logger.info("[Gate 4-5] Tester evaluating %s (attempt %d)", module, attempt)
                try:
                    eval_result = await _with_stage_timeout(
                        self.settings, "tester",
                        evaluate_module(
                            module=module, language=language, contract=contract,
                            attempt=attempt,
                            source_paths=source_paths, context_paths=context_paths,
                            repo_root=repo_root, module_path=module_path,
                        ),
                    )
                except _StageTimeout as exc:
                    self.repo.complete_run(run_id, "blocked", str(exc))
                    await self.state.push_state()
                    return PipelineResult(
                        module=module, status="blocked", message=str(exc),
                        gates_failed=[4, 5],
                    )

                if "PASS" in eval_result.upper():
                    migration_passed = True
                    if 4 not in gates_passed:
                        gates_passed.append(4)
                    if 5 not in gates_passed:
                        gates_passed.append(5)
                    logger.info("Migration PASSED for %s on attempt %d", module, attempt)
                    break
                else:
                    logger.warning("Migration FAILED for %s on attempt %d", module, attempt)
                    if attempt == max_attempts:
                        # Write blocked.md
                        blocked_path = os.path.join(output_dir, "blocked.md")
                        Path(blocked_path).write_text(
                            f"# Blocked: {module}\n\n"
                            f"Migration failed after {max_attempts} self-healing attempts.\n\n"
                            f"## Last Evaluation Result\n{eval_result}\n\n"
                            f"## Recommendation\nRequires human intervention.\n"
                        )
                        self.state.append_failure(
                            f"### {module} — Blocked — {_now()}\n"
                            f"- Attempts: {max_attempts}\n"
                            f"- Last result: {eval_result[:200]}\n"
                        )

            if not migration_passed:
                gates_failed.extend([g for g in [3, 4, 5] if g not in gates_passed])
                self.repo.complete_run(run_id, "blocked", "Failed after 3 self-healing attempts")
                await self._update_progress(module, language, work_item_id, "blocked", gates_passed, gates_failed)
                await self.state.push_state()
                return PipelineResult(
                    module=module,
                    status="blocked",
                    message=f"Blocked after {max_attempts} attempts. See blocked.md.",
                    gates_passed=gates_passed,
                    gates_failed=gates_failed,
                )

            # Pre-commit quality checks
            arch_violations = check_architecture(self.project_root)
            quality_issues = check_directory(os.path.join(self.project_root, "src", "azure-functions", module))
            blocking = [i for i in quality_issues if i.severity == "BLOCK"]
            if arch_violations or blocking:
                logger.warning("Quality gate: %d arch violations, %d blocking issues", len(arch_violations), len(blocking))

            # ─── Gate 6: Reviewer ──────────────────────────────────────
            observability.set_stage("reviewer", attempt=1)
            logger.info("[Gate 6] Running reviewer for %s", module)
            try:
                review_result = await _with_stage_timeout(
                    self.settings, "reviewer",
                    review_module(
                        module=module, language=language,
                        repo_root=repo_root, module_path=module_path,
                    ),
                )
            except _StageTimeout as exc:
                self.repo.complete_run(run_id, "blocked", str(exc))
                await self.state.push_state()
                return PipelineResult(
                    module=module, status="blocked", message=str(exc),
                    gates_failed=[6],
                )

            approved = "APPROVE" in review_result.get("recommendation", "").upper()
            score = review_result.get("confidence_score", 0)

            if approved:
                gates_passed.append(6)
                self.repo.complete_run(run_id, "completed")
                status = "completed"
                message = f"Migration approved (score: {score}/100)"
            else:
                gates_failed.append(6)
                self.repo.complete_run(run_id, "changes_requested")
                status = "changes_requested"
                message = f"Reviewer: {review_result.get('recommendation', 'UNKNOWN')} (score: {score}/100)"

            # ─── Gate 7: Security Review ──────────────────────────────────────
            observability.set_stage("security", attempt=1)
            logger.info("[Gate 7] Running security reviewer for %s", module)
            try:
                security_result = await _with_stage_timeout(
                    self.settings, "security",
                    security_review(
                        module=module, language=language,
                        repo_root=repo_root, module_path=module_path,
                    ),
                )
            except _StageTimeout as exc:
                self.repo.complete_run(run_id, "blocked", str(exc))
                await self.state.push_state()
                return PipelineResult(
                    module=module, status="blocked", message=str(exc),
                    gates_failed=[7],
                )
            if security_result["recommendation"] == "BLOCKED":
                gates_failed.append(7)
            else:
                gates_passed.append(7)

            # Update coverage ratchet
            coverage = review_result.get("coverage")
            if coverage and isinstance(coverage, (int, float)):
                self.state.update_coverage_baseline(int(coverage))

            await self._update_progress(
                module, language, work_item_id, status, gates_passed, gates_failed, score, coverage
            )
            await self.state.push_state()

            return PipelineResult(
                module=module,
                status=status,
                message=message,
                review_score=score,
                coverage=coverage,
                gates_passed=gates_passed,
                gates_failed=gates_failed,
            )

        except Exception as e:
            logger.exception("Pipeline error for %s: %s", module, e)
            self.repo.complete_run(run_id, "failed", str(e))
            await self.state.push_state()
            return PipelineResult(
                module=module,
                status="failed",
                message=f"Internal error: {e}",
                gates_passed=gates_passed,
                gates_failed=gates_failed,
            )

    async def _update_progress(
        self, module, language, work_item_id, status,
        gates_passed, gates_failed, score=None, coverage=None,
    ):
        """Append a session block to migration-progress.txt."""
        block = (
            f"=== Session ===\n"
            f"date: {_now()}\n"
            f"module: {module}\n"
            f"language: {language}\n"
            f"work_item: {work_item_id}\n"
            f"gates_passed: {gates_passed}\n"
            f"gates_failed: {gates_failed}\n"
            f"coverage: {coverage}%\n" if coverage else ""
            f"reviewer_score: {score}/100\n" if score else ""
            f"recommendation: {status}\n"
            f"blocked: {'true' if status == 'blocked' else 'false'}\n"
        )
        self.state.append_progress(block)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
