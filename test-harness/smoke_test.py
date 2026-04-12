"""
E2E Smoke Test — Run both harnesses against the sample Lambda
and verify they produce correct migration outputs.

Requires:
  - Real LLM access (OPENAI_API_KEY or FOUNDRY_PROJECT_ENDPOINT)
  - Both harnesses set up (pip install -r requirements.txt for each)
  - Codex CLI installed (for codex-harness)

Usage:
  python3 test-harness/smoke_test.py [--codex-only | --ms-only | --both]

Cost: ~$1-5 per run depending on model and module size.
"""

import argparse
import json
import os
import shutil
import subprocess

# Load .env from project root
from pathlib import Path as _P
for _env in [_P(__file__).parent.parent / ".env", _P(__file__).parent / ".env"]:
    if _env.exists():
        for _line in _env.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CODEX_DIR = BASE_DIR / "codex-harness"
MS_DIR = BASE_DIR / "ms-agent-harness"

EXPECTED_OUTPUTS = [
    "migration-analysis/{module}/analysis.md",
]

EXPECTED_NO_AWS = [
    "src/azure-functions/{module}/",
]


def setup_module_source(harness_dir: Path, module: str = "order-processor"):
    """Copy sample Lambda into the expected src/lambda/ location."""
    src = harness_dir / "sample" / "lambda"
    dst = harness_dir / "src" / "lambda" / module
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        shutil.copy2(f, dst / f.name)
    print(f"  Setup: copied sample Lambda to {dst}")


def run_codex_harness(module: str = "order-processor") -> dict:
    """Run codex-harness via the CLI script."""
    print("\n" + "=" * 60)
    print("  CODEX HARNESS — Running migration")
    print("=" * 60)

    setup_module_source(CODEX_DIR, module)

    script = CODEX_DIR / ".codex" / "scripts" / "migrate-module.sh"
    if not script.exists():
        return {"status": "error", "message": f"Script not found: {script}"}

    try:
        result = subprocess.run(
            [str(script), module, "python", "WI-SMOKE"],
            capture_output=True, text=True, timeout=3600,
            cwd=str(CODEX_DIR),
        )
        return {
            "status": "completed" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
            "stdout_tail": result.stdout[-2000:] if result.stdout else "",
            "stderr_tail": result.stderr[-1000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def run_ms_harness(module: str = "order-processor") -> dict:
    """Run ms-agent-harness via the REST API (sync endpoint)."""
    print("\n" + "=" * 60)
    print("  MS AGENT HARNESS — Running migration")
    print("=" * 60)

    setup_module_source(MS_DIR, module)

    # Start the API server
    import httpx
    api_url = "http://localhost:8001"

    # Check if already running
    try:
        httpx.get(f"{api_url}/health", timeout=3)
        print("  API already running at :8001")
    except Exception:
        print("  Starting API server on :8001...")
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "orchestrator.api:app", "--port", "8001"],
            cwd=str(MS_DIR),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        import time
        time.sleep(5)  # Wait for startup

    try:
        resp = httpx.post(
            f"{api_url}/migrate/sync",
            json={"module": module, "language": "python", "work_item_id": "WI-SMOKE"},
            timeout=3600,
        )
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def verify_outputs(harness_dir: Path, module: str, harness_name: str) -> list[str]:
    """Verify expected migration outputs exist and are valid."""
    issues = []

    # Check analysis.md exists
    analysis = harness_dir / "migration-analysis" / module / "analysis.md"
    if analysis.exists():
        content = analysis.read_text()
        if len(content) < 50:
            issues.append(f"{harness_name}: analysis.md is too short ({len(content)} chars)")
        else:
            print(f"  ✓ {harness_name}: analysis.md ({len(content)} chars)")
    else:
        issues.append(f"{harness_name}: analysis.md not found")

    # Check for Azure Function code
    azure_dir = harness_dir / "src" / "azure-functions" / module
    if azure_dir.exists():
        azure_files = list(azure_dir.rglob("*"))
        if azure_files:
            print(f"  ✓ {harness_name}: Azure Function code ({len(azure_files)} files)")

            # Check no AWS imports in generated code
            for f in azure_dir.rglob("*.py"):
                content = f.read_text()
                for aws_import in ["import boto3", "from boto3", "@aws-sdk"]:
                    if aws_import in content and not content.startswith("#") and "→" not in content.split(aws_import)[0].split("\n")[-1]:
                        # Skip if it's in a comment explaining the migration
                        lines_with_aws = [l for l in content.split("\n")
                                         if aws_import in l and not l.strip().startswith(("#", "//", "*", "\"\"\"", "'''"))]
                        if lines_with_aws:
                            issues.append(f"{harness_name}: AWS import '{aws_import}' found in {f.name}")
        else:
            issues.append(f"{harness_name}: Azure Function directory empty")
    else:
        issues.append(f"{harness_name}: No Azure Function code generated")

    # Check sprint contract (if exists)
    contract = harness_dir / "migration-analysis" / module / "sprint-contract.json"
    if contract.exists():
        try:
            json.loads(contract.read_text())
            print(f"  ✓ {harness_name}: sprint-contract.json (valid JSON)")
        except json.JSONDecodeError:
            issues.append(f"{harness_name}: sprint-contract.json is invalid JSON")

    # Check review.md
    review = harness_dir / "migration-analysis" / module / "review.md"
    if review.exists():
        content = review.read_text()
        if "APPROVE" in content or "CHANGES_REQUESTED" in content or "BLOCKED" in content:
            print(f"  ✓ {harness_name}: review.md has verdict")
        else:
            issues.append(f"{harness_name}: review.md missing verdict")

    # Check test-results.md
    tests = harness_dir / "migration-analysis" / module / "test-results.md"
    if tests.exists():
        print(f"  ✓ {harness_name}: test-results.md exists")

    return issues


def main():
    parser = argparse.ArgumentParser(description="E2E smoke test for migration harnesses")
    parser.add_argument("--codex-only", action="store_true", help="Only test codex-harness")
    parser.add_argument("--ms-only", action="store_true", help="Only test ms-agent-harness")
    parser.add_argument("--both", action="store_true", default=True, help="Test both (default)")
    parser.add_argument("--module", default="order-processor", help="Module name to migrate")
    args = parser.parse_args()

    module = args.module
    all_issues = []

    # ─── Codex Harness ─────────────────────────────────────────────────
    if not args.ms_only:
        if not shutil.which("codex"):
            print("⚠ Codex CLI not installed — skipping codex-harness test")
        elif not os.environ.get("OPENAI_API_KEY"):
            print("⚠ OPENAI_API_KEY not set — skipping codex-harness test")
        else:
            result = run_codex_harness(module)
            print(f"\n  Result: {result.get('status', 'unknown')}")
            if result.get("status") in ("completed", "blocked"):
                issues = verify_outputs(CODEX_DIR, module, "codex-harness")
                all_issues.extend(issues)

    # ─── MS Agent Harness ──────────────────────────────────────────────
    if not args.codex_only:
        has_foundry = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
        has_openai = os.environ.get("OPENAI_API_KEY")
        if not has_foundry and not has_openai:
            print("⚠ No LLM credentials set — skipping ms-agent-harness test")
        else:
            result = run_ms_harness(module)
            print(f"\n  Result: {result.get('status', 'unknown')}")
            if result.get("status") in ("completed", "blocked", "changes_requested"):
                issues = verify_outputs(MS_DIR, module, "ms-agent-harness")
                all_issues.extend(issues)

    # ─── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  SMOKE TEST SUMMARY")
    print("=" * 60)

    if all_issues:
        print(f"\n  {len(all_issues)} issue(s) found:")
        for issue in all_issues:
            print(f"    ✗ {issue}")
        sys.exit(1)
    else:
        print("\n  ✓ All checks passed")
        sys.exit(0)


if __name__ == "__main__":
    main()
