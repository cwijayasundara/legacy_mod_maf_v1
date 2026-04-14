"""
Security Reviewer Agent — scans migrated code for OWASP vulnerabilities.

Runs after the migration-reviewer. BLOCK findings must be fixed before PR.
Uses both automated scanning (quality/security_scanner.py) and LLM-based
analysis for patterns that regex can't catch.
"""
import logging
from pathlib import Path

from .base import create_agent, run_with_retry
from .tools.file_tools import read_file, search_files, list_directory
from .tools.bicep_tool import validate_bicep
from .quality.security_scanner import scan_directory, SecurityFinding

logger = logging.getLogger("agent.security_reviewer")

def create_security_reviewer(repo_root=None, module_path=None):
    return create_agent(
        role="security-reviewer",
        tools=[read_file, search_files, list_directory, validate_bicep],
        repo_root=repo_root,
        module_path=module_path,
    )

async def security_review(
    module: str, language: str,
    repo_root: str | None = None,
    module_path: str | None = None,
) -> dict:
    """Run automated + LLM security scan on migrated code."""
    azure_dir = f"src/azure-functions/{module}"
    out_dir = Path("migration-analysis") / module
    out_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: Automated regex scan
    automated_findings = scan_directory(azure_dir)

    # Phase 2: LLM-based deep scan
    agent = create_security_reviewer(repo_root=repo_root, module_path=module_path)
    prompt = f"""Security review the migrated Azure Function for module '{module}' ({language}).

Code location: {azure_dir}/

Automated scan found {len(automated_findings)} issues:
{_format_findings(automated_findings)}

Now do a deeper analysis checking for:
1. Logic vulnerabilities the regex scan can't catch (IDOR, auth bypass, race conditions)
2. Input validation gaps (missing sanitization, type coercion issues)
3. Azure-specific security (Managed Identity misuse, Key Vault access, CORS on Function)
4. Dependency vulnerabilities (check requirements.txt / package.json versions)

Write a security review to {out_dir}/security-review.md with:
- Table of all findings (automated + manual)
- Severity: BLOCK / WARN / INFO
- Recommendation: APPROVE / CHANGES_REQUESTED / BLOCKED
"""
    result = await run_with_retry(agent, prompt)

    review_path = out_dir / "security-review.md"
    review_path.write_text(result)

    has_blockers = any(f.severity == "BLOCK" for f in automated_findings) or "BLOCKED" in result.upper()

    return {
        "automated_findings": len(automated_findings),
        "blockers": sum(1 for f in automated_findings if f.severity == "BLOCK"),
        "recommendation": "BLOCKED" if has_blockers else "APPROVE",
        "review_path": str(review_path),
    }

def _format_findings(findings: list[SecurityFinding]) -> str:
    if not findings:
        return "No automated findings."
    lines = ["| File | Line | Category | Severity | Details |", "|---|---|---|---|---|"]
    for f in findings:
        lines.append(f"| {f.file} | {f.line} | {f.category} | {f.severity} | {f.description[:60]} |")
    return "\n".join(lines)
