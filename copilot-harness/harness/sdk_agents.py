"""
Copilot SDK Agents — custom agents for fine-grained control.

Uses github-copilot-sdk for tasks needing more control than CLI auto-delegation.
Currently used for: security review (OWASP scanning with specific patterns).
"""

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("sdk-agents")


async def security_review_via_sdk(module: str, language: str, project_root: str) -> dict:
    """
    Run security review: automated regex scan + optional SDK LLM analysis.
    Returns dict with recommendation and findings count.
    """
    out_dir = Path(project_root) / "migration-analysis" / module
    out_dir.mkdir(parents=True, exist_ok=True)
    azure_dir = Path(project_root) / "src" / "azure-functions" / module

    # Phase 1: Automated regex scan
    findings = _automated_scan(str(azure_dir))

    # Phase 2: LLM-based deep scan via Copilot SDK
    llm_review = ""
    try:
        from github_copilot_sdk import CopilotClient, Agent

        client = CopilotClient(
            api_key=os.environ.get("COPILOT_PROVIDER_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
            provider_type=os.environ.get("COPILOT_PROVIDER_TYPE", "openai"),
            base_url=os.environ.get("COPILOT_PROVIDER_BASE_URL", ""),
        )

        source_content = ""
        if azure_dir.exists():
            for f in list(azure_dir.rglob("*.py")) + list(azure_dir.rglob("*.js")):
                source_content += f"\n--- {f.name} ---\n{f.read_text(errors='replace')[:3000]}\n"

        agent = Agent(client=client, name="security-reviewer",
                      instructions="You are a security reviewer. Scan for OWASP top 10 vulnerabilities.")

        result = await agent.run(
            f"Security review for '{module}' ({language}). "
            f"Automated scan: {len(findings)} issues. "
            f"Check for injection, auth bypass, IDOR, race conditions.\n\n"
            f"Code:\n{source_content[:8000]}"
        )
        llm_review = result.text if hasattr(result, "text") else str(result)

    except ImportError:
        logger.warning("github-copilot-sdk not installed — automated scan only")
        llm_review = "SDK not available."
    except Exception as e:
        logger.warning("SDK review failed: %s", e)
        llm_review = f"SDK review failed: {e}"

    # Write review
    review = f"# Security Review: {module}\n\n## Automated Scan ({len(findings)} findings)\n"
    if findings:
        review += "| File | Line | Category | Severity | Details |\n|---|---|---|---|---|\n"
        for f in findings:
            review += f"| {f['file']} | {f['line']} | {f['category']} | {f['severity']} | {f['detail'][:60]} |\n"
    else:
        review += "No automated findings.\n"
    review += f"\n## LLM Analysis\n{llm_review}\n"

    has_blockers = any(f["severity"] == "BLOCK" for f in findings) or "BLOCKED" in llm_review.upper()
    recommendation = "BLOCKED" if has_blockers else "APPROVE"
    review += f"\n## Recommendation: {recommendation}\n"

    (out_dir / "security-review.md").write_text(review)

    return {
        "automated_findings": len(findings),
        "blockers": sum(1 for f in findings if f["severity"] == "BLOCK"),
        "recommendation": recommendation,
    }


# ─── Automated Security Patterns ──────────────────────────────────────────

_PATTERNS = [
    (r'AKIA[0-9A-Z]{16}', "AWS access key", "BLOCK"),
    (r'sk-[a-zA-Z0-9]{20,}', "OpenAI API key", "BLOCK"),
    (r'ghp_[a-zA-Z0-9]{36}', "GitHub PAT", "BLOCK"),
    (r'password\s*[:=]\s*["\'][^\s"\']{8,}', "Hardcoded password", "BLOCK"),
    (r'AccountKey=[A-Za-z0-9+/=]{44,}', "Azure storage key", "BLOCK"),
    (r'allow_origins\s*=\s*\[\s*["\']?\*', "Permissive CORS", "WARN"),
    (r'verify\s*=\s*False', "SSL verification disabled", "WARN"),
    (r'DEBUG\s*=\s*True', "Debug mode enabled", "WARN"),
]


def _automated_scan(dir_path: str) -> list[dict]:
    root = Path(dir_path)
    if not root.exists():
        return []

    findings = []
    for filepath in root.rglob("*"):
        if not filepath.is_file() or filepath.suffix not in (".py", ".js", ".ts"):
            continue
        is_test = "test" in filepath.name.lower()
        try:
            for i, line in enumerate(filepath.read_text(errors="replace").split("\n"), 1):
                if line.strip().startswith(("#", "//", "*")):
                    continue
                for pattern, desc, severity in _PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        findings.append({
                            "file": str(filepath.relative_to(root)),
                            "line": i,
                            "category": desc,
                            "severity": "INFO" if is_test else severity,
                            "detail": line.strip()[:80],
                        })
        except Exception:
            continue
    return findings
