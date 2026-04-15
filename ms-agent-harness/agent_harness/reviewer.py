"""
Migration Reviewer Agent — Explorer archetype (QUALITY GATE).
Code review and final checkpoint before PR creation.
Read-only: reviews but does NOT modify code.
"""

from pathlib import Path

from .base import create_agent, run_with_retry
from .paths import analysis_dir as _analysis_dir, infra_dir as _infra_dir, migrated_dir
from .tools import read_file, search_files, list_directory, validate_bicep
from .context.chunker import needs_chunking, chunk_file


def create_reviewer(repo_root=None, module_path=None):
    """Create the reviewer agent with read-only tools."""
    return create_agent(
        role="reviewer",
        tools=[read_file, search_files, list_directory, validate_bicep],
        repo_root=repo_root,
        module_path=module_path,
    )


async def review_module(
    module: str, language: str,
    repo_root: str | None = None,
    module_path: str | None = None,
) -> dict:
    """
    Perform the 8-point quality gate review on a migrated Azure Function module.

    Reads the analysis, test results, sprint contract, and source code.
    Produces review.md with the 8-point checklist, confidence score,
    and recommendation (APPROVE / CHANGES_REQUESTED / BLOCKED).

    Args:
        module: Name of the module being reviewed.
        language: Programming language of the module.

    Returns:
        Dict with keys: recommendation, confidence, review_path, blocking_issues.
    """
    agent = create_reviewer(repo_root=repo_root, module_path=module_path)

    analysis_dir = _analysis_dir(module)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    review_path = analysis_dir / "review.md"
    azure_func_dir = migrated_dir(module)
    infra_dir = _infra_dir(module)

    # Gather all context files
    context_sections = []

    # Analysis
    analysis_path = analysis_dir / "analysis.md"
    if analysis_path.exists():
        context_sections.append(
            f"## Analyzer Output\n{analysis_path.read_text(encoding='utf-8')}"
        )

    # Sprint contract
    contract_path = analysis_dir / "sprint-contract.json"
    if contract_path.exists():
        context_sections.append(
            f"## Sprint Contract\n```json\n{contract_path.read_text(encoding='utf-8')}\n```"
        )

    # Test results
    test_results_path = analysis_dir / "test-results.md"
    if test_results_path.exists():
        context_sections.append(
            f"## Test Results\n{test_results_path.read_text(encoding='utf-8')}"
        )

    # Failure reports (if any)
    failures_path = analysis_dir / "eval-failures.json"
    if failures_path.exists():
        context_sections.append(
            f"## Failure Reports\n```json\n{failures_path.read_text(encoding='utf-8')}\n```"
        )

    # Migrated source files
    source_sections = []
    if azure_func_dir.exists():
        for fpath in sorted(azure_func_dir.rglob("*")):
            if fpath.is_file() and not fpath.name.startswith("."):
                if needs_chunking(fpath):
                    chunks = chunk_file(fpath)
                    for i, chunk in enumerate(chunks):
                        source_sections.append(
                            f"--- {fpath} (chunk {i + 1}/{len(chunks)}) ---\n{chunk}"
                        )
                else:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    source_sections.append(f"--- {fpath} ---\n{content}")

    if source_sections:
        context_sections.append(
            f"## Migrated Source Code\n" + "\n\n".join(source_sections)
        )

    # Infrastructure files
    if infra_dir.exists():
        for fpath in sorted(infra_dir.rglob("*")):
            if fpath.is_file():
                content = fpath.read_text(encoding="utf-8", errors="replace")
                context_sections.append(
                    f"## Infrastructure: {fpath.name}\n```\n{content}\n```"
                )

    # Read learned rules
    learned_rules_path = Path("state/learned-rules.md")
    if learned_rules_path.exists():
        context_sections.append(
            f"## Learned Rules\n{learned_rules_path.read_text(encoding='utf-8')}"
        )

    # Read coverage baseline
    baseline_path = Path("state/coverage-baseline.txt")
    if baseline_path.exists():
        context_sections.append(
            f"## Coverage Baseline\n{baseline_path.read_text(encoding='utf-8').strip()}%"
        )

    full_context = "\n\n".join(context_sections)

    prompt = (
        f"Review the migrated Azure Function module '{module}' ({language}).\n\n"
        f"{full_context}\n\n"
        f"Perform the 8-point quality gate review.\n"
        f"Write your review to: {review_path}\n"
        f"Follow the output format from your system instructions exactly.\n"
        f"Return your recommendation as one of: APPROVE, CHANGES_REQUESTED, BLOCKED."
    )

    result = await run_with_retry(agent, prompt, max_retries=3)

    # Write the review
    review_path.write_text(result, encoding="utf-8")

    # Parse recommendation from output. Tolerate several formats the LLM tends
    # to produce: "## Recommendation: X", "Recommendation: **X**", trailing
    # prose like "my recommendation is BLOCKED", all case/whitespace variants.
    import re as _re
    recommendation = "CHANGES_REQUESTED"  # default conservative
    norm = result.upper()
    # Prefer an explicit labeled verdict anywhere in the doc.
    labeled = _re.search(
        r"RECOMMENDATION[^A-Z]{0,40}(APPROVE|BLOCKED|CHANGES[_ ]REQUESTED)",
        norm,
    )
    if labeled:
        verdict = labeled.group(1).replace(" ", "_")
        recommendation = "APPROVE" if verdict == "APPROVE" else (
            "BLOCKED" if verdict == "BLOCKED" else "CHANGES_REQUESTED"
        )
    else:
        # Fallback: look at final ~400 chars for a bolded / prose verdict.
        tail = norm[-400:]
        if _re.search(r"\bAPPROVE\b", tail) and "NOT APPROVE" not in tail:
            recommendation = "APPROVE"
        elif _re.search(r"\bBLOCKED\b", tail):
            recommendation = "BLOCKED"

    # Parse confidence score
    confidence = 0
    import re
    confidence_match = re.search(r"Confidence Score:\s*(\d+)/100", result)
    if confidence_match:
        confidence = int(confidence_match.group(1))

    # Extract blocking issues
    blocking_issues = []
    blocking_section = re.search(
        r"### Blocking\n(.*?)(?:\n###|\n## |\Z)", result, re.DOTALL
    )
    if blocking_section:
        for line in blocking_section.group(1).strip().split("\n"):
            line = line.strip()
            if line.startswith("- "):
                blocking_issues.append(line[2:])

    return {
        "recommendation": recommendation,
        "confidence": confidence,
        "review_path": str(review_path),
        "blocking_issues": blocking_issues,
    }
