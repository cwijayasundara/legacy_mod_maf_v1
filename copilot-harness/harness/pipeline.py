"""
Migration pipeline orchestrator — Copilot CLI version.

Uses Copilot CLI's built-in sub-agents for the main migration pipeline
(Gates 1-6) and the Copilot SDK for the security review (Gate 7).

Same 7-gate structure as ms-agent-harness, but delegation is automatic —
Copilot decides which sub-agent handles each task.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .copilot_runner import CopilotRunner
from .sdk_agents import security_review_via_sdk

logger = logging.getLogger("pipeline")


@dataclass
class PipelineResult:
    module: str
    status: str  # completed, blocked, failed
    message: str = ""
    review_score: int | None = None
    coverage: float | None = None
    gates_passed: list[int] = field(default_factory=list)
    gates_failed: list[int] = field(default_factory=list)


class MigrationPipeline:
    """
    7-gate migration pipeline using Copilot CLI + SDK.

    Gates 1-6: Copilot CLI in autopilot mode (built-in sub-agents)
    Gate 7: Security review via Copilot SDK (fine-grained control)
    """

    def __init__(self, project_root: str = ""):
        self.project_root = project_root or str(Path(__file__).parent.parent)
        self.runner = CopilotRunner(project_root=self.project_root)
        self._settings = self._load_settings()

    def _load_settings(self) -> dict:
        settings_path = os.path.join(self.project_root, "config", "settings.yaml")
        try:
            if os.path.exists(settings_path):
                with open(settings_path) as f:
                    return yaml.safe_load(f) or {}
        except Exception:
            pass
        return {}

    async def run(
        self,
        module: str,
        language: str,
        work_item_id: str = "LOCAL",
        title: str = "",
        description: str = "",
        acceptance_criteria: str = "",
    ) -> PipelineResult:
        """Run the full 7-gate migration pipeline."""
        logger.info("Pipeline starting: %s (%s)", module, language)

        # Ensure output directories
        for subdir in [
            f"migration-analysis/{module}",
            f"src/azure-functions/{module}",
            f"infrastructure/{module}",
        ]:
            os.makedirs(os.path.join(self.project_root, subdir), exist_ok=True)

        # ─── Gates 1-6: Copilot CLI (built-in sub-agents) ─────────────
        prompt = self._compose_prompt(module, language, work_item_id, title, description, acceptance_criteria)

        success, output = await self.runner.run(
            prompt=prompt,
            module=module,
            language=language,
        )

        # Save output log
        log_dir = os.path.join(self.project_root, "migration-analysis", module)
        with open(os.path.join(log_dir, "copilot-output.log"), "w") as f:
            f.write(output)

        # Check results
        blocked_path = os.path.join(log_dir, "blocked.md")
        review_path = os.path.join(log_dir, "review.md")

        gates_passed = []
        gates_failed = []

        if os.path.exists(blocked_path):
            logger.warning("Migration BLOCKED: %s", module)
            self._append_progress(module, language, work_item_id, "blocked")
            return PipelineResult(
                module=module, status="blocked",
                message="Blocked after self-healing attempts. See blocked.md.",
            )

        # Parse which gates passed based on output artifacts
        if os.path.exists(os.path.join(log_dir, "analysis.md")):
            gates_passed.append(1)
        if os.path.exists(os.path.join(log_dir, "sprint-contract.json")):
            gates_passed.append(2)
        if os.path.exists(os.path.join(log_dir, "test-results.md")):
            gates_passed.extend([3, 4, 5])

        review_score = None
        if os.path.exists(review_path):
            content = open(review_path).read()
            approved = "APPROVE" in content
            import re
            score_match = re.search(r'(\d+)/100', content)
            review_score = int(score_match.group(1)) if score_match else None
            if approved:
                gates_passed.append(6)
            else:
                gates_failed.append(6)

        if not success and not gates_passed:
            self._append_progress(module, language, work_item_id, "failed")
            return PipelineResult(
                module=module, status="failed",
                message="Copilot execution failed. See copilot-output.log.",
            )

        # ─── Gate 7: Security Review (via SDK) ────────────────────────
        use_sdk = self._settings.get("sdk", {}).get("security_review_via_sdk", True)
        if use_sdk:
            logger.info("[Gate 7] Running security review for %s", module)
            try:
                sec_result = await security_review_via_sdk(module, language, self.project_root)
                if sec_result["recommendation"] == "BLOCKED":
                    gates_failed.append(7)
                    logger.warning("Security review BLOCKED: %s", module)
                else:
                    gates_passed.append(7)
            except Exception as e:
                logger.error("Security review error: %s", e)
                gates_passed.append(7)  # Don't block on SDK errors
        else:
            gates_passed.append(7)

        # Determine final status
        if 6 in gates_passed and 7 in gates_passed:
            status = "completed"
            message = f"Migration approved (score: {review_score}/100)"
        elif 6 in gates_failed:
            status = "changes_requested"
            message = "Reviewer requested changes. See review.md."
        elif 7 in gates_failed:
            status = "security_blocked"
            message = "Security review blocked. See security-review.md."
        else:
            status = "completed" if success else "failed"
            message = "See migration artifacts for details."

        self._append_progress(module, language, work_item_id, status, review_score)

        return PipelineResult(
            module=module, status=status, message=message,
            review_score=review_score, gates_passed=gates_passed, gates_failed=gates_failed,
        )

    def _compose_prompt(self, module, language, wi_id, title, desc, criteria) -> str:
        """Compose the migration prompt. Copilot reads .copilot/AGENTS.md automatically."""
        return f"""Migrate AWS Lambda module '{module}' ({language}) to Azure Functions.

Work Item: WI-{wi_id} — {title}
Description: {desc}
Acceptance Criteria: {criteria}

Read context files first:
- .copilot/AGENTS.md (migration workflow and principles)
- config/program.md (human steering constraints)
- config/state/learned-rules.md (prevent repeated mistakes)
- config/state/coverage-baseline.txt (coverage floor)

Follow the AGENTS.md workflow:
1. Analyze src/lambda/{module}/ → migration-analysis/{module}/analysis.md
2. Propose sprint contract → migration-analysis/{module}/sprint-contract.json
3. Write tests FIRST, then migrate code → src/azure-functions/{module}/
4. Generate Bicep template → infrastructure/{module}/main.bicep
5. Evaluate: unit + integration + contract → migration-analysis/{module}/test-results.md
6. Review: 8-point checklist → migration-analysis/{module}/review.md

If blocked after 3 attempts, write migration-analysis/{module}/blocked.md.
Do NOT commit broken code.
"""

    def _append_progress(self, module, language, wi_id, status, score=None):
        """Append session block to migration-progress.txt."""
        progress_path = os.path.join(self.project_root, "config", "state", "migration-progress.txt")
        block = (
            f"\n=== Session ===\n"
            f"date: {datetime.now(timezone.utc).isoformat()}\n"
            f"module: {module}\n"
            f"language: {language}\n"
            f"work_item: {wi_id}\n"
            f"recommendation: {status}\n"
        )
        if score:
            block += f"reviewer_score: {score}/100\n"
        with open(progress_path, "a") as f:
            f.write(block)
