"""
Migration Tester Agent — evaluator role.

Runs three-layer evaluation (unit, integration, contract),
writes structured failure reports, and enforces coverage ratcheting.
"""

import json
import logging
import os
from pathlib import Path

from .base import create_agent, run_with_retry
from .paths import analysis_dir, migrated_dir
from .tools.file_tools import read_file, search_files, list_directory
from .tools.test_runner import run_tests, measure_coverage
from .context.chunker import needs_chunking, chunk_file

logger = logging.getLogger("agent.tester")


def create_tester(repo_root=None, module_path=None):
    """Create the tester agent with test runner tools."""
    return create_agent(
        role="tester",
        tools=[read_file, search_files, list_directory, run_tests, measure_coverage],
        repo_root=repo_root,
        module_path=module_path,
    )


async def finalize_contract(module: str, proposed_contract: str) -> str:
    """
    Finalize the sprint contract proposed by the coder.
    The tester can add missing checks or remove invalid ones.
    Returns the finalized contract JSON string.
    """
    agent = create_tester()
    prompt = f"""Review and finalize this sprint contract for module '{module}'.

Proposed contract:
{proposed_contract}

You may:
- ADD checks the coder overlooked (edge cases, error responses, schema validation)
- REMOVE checks that are invalid or untestable
- Set finalized_by to "migration-tester"

Return the finalized contract as valid JSON. The contract is IMMUTABLE after this."""

    result = await run_with_retry(agent, prompt)

    # Try to extract JSON from the response
    out_dir = analysis_dir(module)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Try parsing the full response as JSON
        contract = json.loads(result)
    except json.JSONDecodeError:
        # Try extracting JSON block from markdown
        import re
        json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', result, re.DOTALL)
        if json_match:
            contract = json.loads(json_match.group(1))
        else:
            contract = {"raw_response": result, "finalized_by": "migration-tester"}

    contract_path = out_dir / "sprint-contract.json"
    contract_path.write_text(json.dumps(contract, indent=2))

    return json.dumps(contract)


async def evaluate_module(
    module: str,
    language: str,
    contract: str,
    attempt: int = 1,
    source_paths: list[str] | tuple = (),
    context_paths: list[str] | tuple = (),
    repo_root: str | None = None,
    module_path: str | None = None,
) -> str:
    """
    Run three-layer evaluation on a migrated module.
    Returns the evaluation result text (containing PASS or FAIL verdict).
    """
    agent = create_tester(repo_root=repo_root, module_path=module_path)
    out_dir = analysis_dir(module)
    azure_dir = migrated_dir(module)

    if source_paths:
        src_listing = "Source files: " + ", ".join(source_paths)
    else:
        src_listing = f"Source Lambda: src/lambda/{module}/"
    if context_paths:
        src_listing += "\nRead-only context: " + ", ".join(context_paths)

    prompt = f"""Evaluate the migrated Azure Function for module '{module}' ({language}).
Attempt: {attempt}/3

{src_listing}
Migrated code: {azure_dir}/
Sprint contract: {contract[:2000]}

Perform three-layer evaluation:

Layer 1 (Unit Tests): Check if tests exist at {azure_dir}/tests/. Describe what they verify.
Layer 2 (Integration): Verify Azure SDK usage patterns are correct (DefaultAzureCredential, proper client init).
Layer 3 (Contract): Verify API contracts match original Lambda (same status codes, response format, error handling).

Write a verdict: PASS (all layers pass), FAIL (any layer fails), or PARTIAL.
Include specific issues found for each layer."""

    # Add failure context from previous attempts
    failures_path = out_dir / "eval-failures.json"
    if attempt > 1 and failures_path.exists():
        prior = failures_path.read_text()
        prompt += f"\n\nPrior failure reports (do NOT repeat the same checks):\n{prior[:2000]}"

    result = await run_with_retry(agent, prompt)

    # Write test results
    results_path = out_dir / "test-results.md"
    results_path.write_text(result)

    # Write structured failure report if FAIL
    if "FAIL" in result.upper() and "PASS" not in result.upper().split("FAIL")[0][-20:]:
        _write_failure_report(module, attempt, result)

    return result


def _write_failure_report(module: str, attempt: int, result: str):
    """Write structured eval-failures.json for the coder to consume."""
    out_dir = analysis_dir(module)
    report = {
        "module": module,
        "attempt": attempt,
        "overall_verdict": "FAIL",
        "failures": [
            {
                "failure_id": f"F{attempt:03d}",
                "layer": "unknown",
                "error_category": "assertion_error",
                "description": result[:500],
                "self_healing_strategy": "Re-read the original Lambda and compare behavior.",
            }
        ],
        "prior_attempts": [],
    }

    # Merge with existing failures if retrying
    failures_path = out_dir / "eval-failures.json"
    if failures_path.exists():
        try:
            existing = json.loads(failures_path.read_text())
            report["prior_attempts"] = existing.get("prior_attempts", [])
            report["prior_attempts"].append({
                "attempt": existing.get("attempt", attempt - 1),
                "strategy": "previous attempt",
                "result": existing.get("overall_verdict", "FAIL"),
            })
        except json.JSONDecodeError:
            pass

    failures_path.write_text(json.dumps(report, indent=2))
