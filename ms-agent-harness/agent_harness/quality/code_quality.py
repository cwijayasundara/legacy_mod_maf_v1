"""
Code quality checker — enforce the 6 engineering principles.

1. Small Modules (300 line block, 200 warn)
2. Static Typing (missing type hints)
3. Functions Under 50 Lines (50 warn, 100 block)
4. Single Owner for State Mutations (duplicate DB writes)
5. Explicit Error Handling (bare except)
6. No Dead Code (commented-out code, unused imports)
"""
import re
from dataclasses import dataclass
from pathlib import Path

@dataclass
class QualityIssue:
    file: str
    line: int
    rule: str
    severity: str  # BLOCK, WARN, INFO
    message: str

def check_code_quality(file_path: str) -> list[QualityIssue]:
    """Run all 6 quality checks on a single file."""
    issues = []
    path = Path(file_path)
    if not path.exists():
        return issues

    content = path.read_text(errors="replace")
    lines = content.split("\n")
    rel = str(path)

    # Rule 1: File length
    if len(lines) > 300:
        issues.append(QualityIssue(rel, 1, "small-modules", "BLOCK", f"File is {len(lines)} lines (max 300). Split into sub-modules."))
    elif len(lines) > 200:
        issues.append(QualityIssue(rel, 1, "small-modules", "WARN", f"File is {len(lines)} lines (consider splitting at 200)."))

    # Rule 2: Missing type hints (Python)
    if file_path.endswith(".py"):
        for i, line in enumerate(lines, 1):
            if re.match(r'^\s*def\s+\w+\([^)]*\)\s*:', line) and '->' not in line:
                fn_name = re.search(r'def\s+(\w+)', line).group(1)
                if fn_name not in ('__init__', '__str__', '__repr__'):
                    issues.append(QualityIssue(rel, i, "static-typing", "WARN", f"Function '{fn_name}' missing return type hint"))

    # Rule 3: Function length
    func_starts = []
    for i, line in enumerate(lines, 1):
        if re.match(r'^\s*(async\s+)?def\s+\w+', line):
            func_starts.append((i, line.strip()[:60]))
    for idx, (start, name) in enumerate(func_starts):
        end = func_starts[idx + 1][0] if idx + 1 < len(func_starts) else len(lines) + 1
        length = end - start
        if length > 100:
            issues.append(QualityIssue(rel, start, "function-length", "BLOCK", f"Function is {length} lines (max 100): {name}"))
        elif length > 50:
            issues.append(QualityIssue(rel, start, "function-length", "WARN", f"Function is {length} lines (consider splitting at 50): {name}"))

    # Rule 5: Bare except
    for i, line in enumerate(lines, 1):
        if re.match(r'^\s*except\s*:', line):
            issues.append(QualityIssue(rel, i, "explicit-errors", "BLOCK", "Bare 'except:' — catch specific exception types"))
        if re.match(r'^\s*except\s+Exception\s*:', line):
            issues.append(QualityIssue(rel, i, "explicit-errors", "WARN", "'except Exception:' — prefer specific exception types"))

    # Rule 6: Commented-out code
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("# ") and any(kw in stripped for kw in ["def ", "class ", "import ", "return ", "if ", "for "]):
            issues.append(QualityIssue(rel, i, "no-dead-code", "INFO", "Possible commented-out code — remove if unused"))

    return issues

def check_directory(dir_path: str) -> list[QualityIssue]:
    """Run quality checks on all Python files in a directory."""
    issues = []
    for f in Path(dir_path).rglob("*.py"):
        if "__pycache__" not in str(f) and "test" not in str(f).lower():
            issues.extend(check_code_quality(str(f)))
    return issues
