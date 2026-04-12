"""
Comparison harness — diff outputs between codex-harness and ms-agent-harness.

Run after smoke_test.py has executed both frameworks on the same module.
Compares the quality and completeness of migration outputs.

Usage:
  python3 test-harness/compare.py [--module order-processor]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Load .env from project root
for _env in [Path(__file__).parent.parent / ".env", Path(__file__).parent / ".env"]:
    if _env.exists():
        for _line in _env.read_text().splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

BASE_DIR = Path(__file__).parent.parent
CODEX_DIR = BASE_DIR / "codex-harness"
MS_DIR = BASE_DIR / "ms-agent-harness"
COPILOT_DIR = BASE_DIR / "copilot-harness"


def compare_module(module: str):
    """Compare migration outputs for a module between both harnesses."""
    print(f"\n{'=' * 70}")
    print(f"  COMPARISON: {module}")
    print(f"{'=' * 70}\n")

    codex_out = CODEX_DIR / "migration-analysis" / module
    ms_out = MS_DIR / "migration-analysis" / module
    copilot_out = COPILOT_DIR / "migration-analysis" / module

    codex_available = codex_out.exists() and any(codex_out.iterdir())
    ms_available = ms_out.exists() and any(ms_out.iterdir())
    copilot_available = copilot_out.exists() and any(copilot_out.iterdir())

    if not codex_available:
        print("  ⚠ codex-harness: no output found — run smoke_test.py --codex-only first")
    if not ms_available:
        print("  ⚠ ms-agent-harness: no output found — run smoke_test.py --ms-only first")
    if not copilot_available:
        print("  ⚠ copilot-harness: no output found — run smoke_test.py --copilot-only first")

    if not codex_available and not ms_available and not copilot_available:
        return

    # Build the list of harnesses to evaluate
    harnesses = []
    if codex_available:
        harnesses.append(("codex", codex_out, CODEX_DIR))
    if ms_available:
        harnesses.append(("ms-agent", ms_out, MS_DIR))
    if copilot_available:
        harnesses.append(("copilot", copilot_out, COPILOT_DIR))

    print()

    results = []

    # ─── 1. Analysis Completeness ──────────────────────────────────────
    print("  1. Analysis Completeness")
    for name, out_dir, _ in harnesses:
        analysis = out_dir / "analysis.md"
        if analysis.exists():
            content = analysis.read_text()
            has_deps = "AWS Dependencies" in content or "AWS Service" in content
            has_complexity = any(w in content for w in ["LOW", "MEDIUM", "HIGH"])
            has_logic = "Business Logic" in content
            score = sum([has_deps, has_complexity, has_logic])
            results.append((f"{name}-analysis", score, 3))
            print(f"     {name}: deps={has_deps} complexity={has_complexity} logic={has_logic} ({score}/3)")
        else:
            results.append((f"{name}-analysis", 0, 3))
            print(f"     {name}: MISSING")

    # ─── 2. Sprint Contract ────────────────────────────────────────────
    print("\n  2. Sprint Contract")
    for name, out_dir, _ in harnesses:
        contract = out_dir / "sprint-contract.json"
        if contract.exists():
            try:
                data = json.loads(contract.read_text())
                has_unit = "unit_checks" in data.get("contract", data)
                has_api = "contract_checks" in data.get("contract", data)
                has_arch = "architecture_checks" in data.get("contract", data)
                score = sum([has_unit, has_api, has_arch])
                results.append((f"{name}-contract", score, 3))
                print(f"     {name}: unit={has_unit} api={has_api} arch={has_arch} ({score}/3)")
            except json.JSONDecodeError:
                results.append((f"{name}-contract", 0, 3))
                print(f"     {name}: INVALID JSON")
        else:
            results.append((f"{name}-contract", 0, 3))
            print(f"     {name}: not generated")

    # ─── 3. Test Results ───────────────────────────────────────────────
    print("\n  3. Test Results")
    for name, out_dir, _ in harnesses:
        tests = out_dir / "test-results.md"
        if tests.exists():
            content = tests.read_text()
            has_unit = "Layer 1" in content or "Unit Test" in content
            has_integ = "Layer 2" in content or "Integration" in content
            has_contract = "Layer 3" in content or "Contract" in content
            has_verdict = any(v in content for v in ["PASS", "FAIL", "PARTIAL"])
            coverage_match = re.search(r'(\d+)%', content)
            coverage = int(coverage_match.group(1)) if coverage_match else 0
            score = sum([has_unit, has_integ, has_contract, has_verdict])
            results.append((f"{name}-tests", score, 4))
            print(f"     {name}: unit={has_unit} integ={has_integ} contract={has_contract} verdict={has_verdict} coverage={coverage}% ({score}/4)")
        else:
            results.append((f"{name}-tests", 0, 4))
            print(f"     {name}: not generated")

    # ─── 4. Review Quality ─────────────────────────────────────────────
    print("\n  4. Review Quality")
    for name, out_dir, _ in harnesses:
        review = out_dir / "review.md"
        if review.exists():
            content = review.read_text()
            has_checklist = "PASS" in content and ("Business Logic" in content or "Check" in content)
            has_score = "Confidence" in content or "/100" in content
            has_verdict = any(v in content for v in ["APPROVE", "CHANGES_REQUESTED", "BLOCKED"])
            score_match = re.search(r'(\d+)/100', content)
            review_score = int(score_match.group(1)) if score_match else 0
            score = sum([has_checklist, has_score, has_verdict])
            results.append((f"{name}-review", score, 3))
            print(f"     {name}: checklist={has_checklist} score={review_score}/100 verdict={has_verdict} ({score}/3)")
        else:
            results.append((f"{name}-review", 0, 3))
            print(f"     {name}: not generated")

    # ─── 5. Azure Function Code ────────────────────────────────────────
    print("\n  5. Azure Function Code")
    for name, _, base_dir in harnesses:
        azure_dir = base_dir / "src" / "azure-functions" / module
        if azure_dir.exists():
            files = list(azure_dir.rglob("*.*"))
            has_handler = any("function_app" in f.name or "index" in f.name for f in files)
            has_tests = any("test" in f.name.lower() for f in files)
            has_requirements = any(f.name in ("requirements.txt", "package.json") for f in files)
            has_host = any(f.name == "host.json" for f in files)

            # Check for AWS imports in code (not comments)
            aws_clean = True
            for f in files:
                if f.suffix in (".py", ".js"):
                    for line in f.read_text().split("\n"):
                        stripped = line.strip()
                        if not stripped.startswith(("#", "//", "*", "\"\"\"")) and \
                           any(pkg in stripped for pkg in ["import boto3", "from boto3", "require('@aws-sdk"]):
                            aws_clean = False
                            break

            score = sum([has_handler, has_tests, has_requirements, has_host, aws_clean])
            results.append((f"{name}-code", score, 5))
            print(f"     {name}: handler={has_handler} tests={has_tests} deps={has_requirements} host={has_host} aws_clean={aws_clean} ({score}/5)")
        else:
            results.append((f"{name}-code", 0, 5))
            print(f"     {name}: no code generated")

    # ─── Summary ───────────────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print("  SCORECARD")
    print(f"{'─' * 70}")

    # Score each harness
    for label in ["codex", "ms", "copilot"]:
        prefix = label + "-" if label != "ms" else "ms-"
        total = sum(s for n, s, _ in results if n.startswith(prefix) or n.startswith(label))
        maximum = sum(m for n, _, m in results if n.startswith(prefix) or n.startswith(label))
        name_map = {"codex": "codex-harness", "ms": "ms-agent-harness", "copilot": "copilot-harness"}
        if maximum:
            print(f"  {name_map[label]:20s} {total}/{maximum} ({total/maximum*100:.0f}%)")
        else:
            print(f"  {name_map[label]:20s} no data")

    if codex_max and ms_max:
        diff = (codex_total / codex_max) - (ms_total / ms_max)
        if abs(diff) < 0.1:
            print(f"\n  Verdict: EQUIVALENT (within 10%)")
        elif diff > 0:
            print(f"\n  Verdict: codex-harness scored higher by {diff*100:.0f}%")
        else:
            print(f"\n  Verdict: ms-agent-harness scored higher by {-diff*100:.0f}%")


def main():
    parser = argparse.ArgumentParser(description="Compare migration outputs between harnesses")
    parser.add_argument("--module", default="order-processor")
    args = parser.parse_args()
    compare_module(args.module)


if __name__ == "__main__":
    main()
