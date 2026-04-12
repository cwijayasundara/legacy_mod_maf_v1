"""
Security scanner — detect OWASP top 10 vulnerability patterns.
"""
import re
from dataclasses import dataclass
from pathlib import Path

@dataclass
class SecurityFinding:
    file: str
    line: int
    category: str
    severity: str  # BLOCK, WARN, INFO
    description: str

SECRET_PATTERNS = [
    (r'AKIA[0-9A-Z]{16}', "AWS access key", "BLOCK"),
    (r'sk-[a-zA-Z0-9]{20,}', "OpenAI API key", "BLOCK"),
    (r'ghp_[a-zA-Z0-9]{36}', "GitHub PAT", "BLOCK"),
    (r'password\s*[:=]\s*["\'][^\s"\']{8,}', "Hardcoded password", "BLOCK"),
    (r'AccountKey=[A-Za-z0-9+/=]{44,}', "Azure storage key", "BLOCK"),
    (r'Bearer\s+[A-Za-z0-9._~+/=-]{20,}', "Bearer token", "BLOCK"),
]

INJECTION_PATTERNS = [
    (r'f["\'].*\{.*\}.*(?:SELECT|INSERT|UPDATE|DELETE|DROP)', "SQL injection via f-string", "BLOCK"),
    (r'\.format\(.*\).*(?:SELECT|INSERT|UPDATE|DELETE)', "SQL injection via .format()", "BLOCK"),
    (r'subprocess\.(?:call|run|Popen)\(.*shell\s*=\s*True', "Command injection (shell=True)", "BLOCK"),
    (r'os\.system\(', "Command injection (os.system)", "BLOCK"),
    (r'eval\(', "Code injection (eval)", "BLOCK"),
    (r'exec\(', "Code injection (exec)", "WARN"),
]

CONFIG_PATTERNS = [
    (r'allow_origins\s*=\s*\[\s*["\']?\*', "Permissive CORS (allow all origins)", "WARN"),
    (r'DEBUG\s*=\s*True', "Debug mode enabled", "WARN"),
    (r'verify\s*=\s*False', "SSL verification disabled", "WARN"),
]

def scan_file(file_path: str) -> list[SecurityFinding]:
    """Scan a single file for security issues."""
    findings = []
    path = Path(file_path)
    if not path.exists():
        return findings

    is_test = "test" in str(path).lower()
    content = path.read_text(errors="replace")
    rel = str(path)

    for i, line in enumerate(content.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue

        for pattern, desc, severity in SECRET_PATTERNS + INJECTION_PATTERNS + CONFIG_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                actual_severity = "INFO" if is_test else severity
                findings.append(SecurityFinding(rel, i, desc, actual_severity, f"Pattern matched: {stripped[:80]}"))

    return findings

def scan_directory(dir_path: str) -> list[SecurityFinding]:
    """Scan all source files in a directory."""
    findings = []
    for ext in ["*.py", "*.js", "*.ts", "*.java", "*.cs"]:
        for f in Path(dir_path).rglob(ext):
            if "__pycache__" not in str(f) and "node_modules" not in str(f):
                findings.extend(scan_file(str(f)))
    return findings
