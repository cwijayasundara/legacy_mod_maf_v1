"""
AST tools — parse source code to extract structure, imports, and dependencies.

Uses regex-based parsing (portable, no tree-sitter binary dependency).
Supports Python, Node.js, Java, and C#.
"""

import re
from pathlib import Path

from agent_framework import tool

# AWS SDK import patterns per language
AWS_PATTERNS = {
    "python": [
        (r'^\s*import\s+boto3', "boto3"),
        (r'^\s*from\s+boto3', "boto3"),
        (r'boto3\.client\([\'"](\w+)[\'"]\)', "boto3.client({})"),
        (r'boto3\.resource\([\'"](\w+)[\'"]\)', "boto3.resource({})"),
    ],
    "node": [
        (r'require\([\'"]@aws-sdk/client-(\w+)[\'"]\)', "@aws-sdk/client-{}"),
        (r'from\s+[\'"]@aws-sdk/client-(\w+)[\'"]', "@aws-sdk/client-{}"),
        (r'require\([\'"]@aws-sdk/lib-(\w+)[\'"]\)', "@aws-sdk/lib-{}"),
    ],
    "java": [
        (r'import\s+com\.amazonaws\.services\.(\w+)', "com.amazonaws.services.{}"),
        (r'import\s+software\.amazon\.awssdk\.services\.(\w+)', "software.amazon.awssdk.services.{}"),
    ],
    "csharp": [
        (r'using\s+Amazon\.(\w+)', "Amazon.{}"),
        (r'using\s+AWSSDK\.(\w+)', "AWSSDK.{}"),
    ],
}

# Azure SDK equivalents
AWS_TO_AZURE = {
    "dynamodb": ("Cosmos DB", "azure-cosmos"),
    "dynamodbv2": ("Cosmos DB", "azure-cosmos"),
    "s3": ("Blob Storage", "azure-storage-blob"),
    "sqs": ("Queue Storage", "azure-storage-queue"),
    "sns": ("Event Grid", "azure-eventgrid"),
    "secretsmanager": ("Key Vault", "azure-keyvault-secrets"),
    "secrets-manager": ("Key Vault", "azure-keyvault-secrets"),
    "lambda": ("Functions", "azure-functions"),
    "stepfunctions": ("Durable Functions", "azure-functions-durable"),
    "cloudwatch": ("Monitor", "azure-monitor"),
    "events": ("Event Grid", "azure-eventgrid"),
}


@tool(approval_mode="never_require")
def parse_imports(file_path: str, language: str) -> str:
    """
    Parse a source file and extract all import statements.
    Returns a list of imports, one per line.
    """
    try:
        content = Path(file_path).read_text(errors="replace")
    except Exception as e:
        return f"ERROR: {e}"

    patterns = {
        "python": r'^\s*(import\s+\S+|from\s+\S+\s+import\s+.*)',
        "node": r'(?:const|let|var|import)\s+.*(?:require|from)\s*\(?[\'"]([^"\']+)',
        "java": r'^\s*import\s+[\w.]+;',
        "csharp": r'^\s*using\s+[\w.]+;',
    }
    pattern = patterns.get(language, patterns["python"])
    matches = re.findall(pattern, content, re.MULTILINE)
    return "\n".join(matches) if matches else "No imports found"


@tool(approval_mode="never_require")
def extract_functions(file_path: str, language: str) -> str:
    """
    Extract function/method signatures from a source file.
    Returns name, line number, and parameter list.
    """
    try:
        lines = Path(file_path).read_text(errors="replace").split("\n")
    except Exception as e:
        return f"ERROR: {e}"

    patterns = {
        "python": r'^\s*(?:async\s+)?def\s+(\w+)\s*\((.*?)\)',
        "node": r'(?:async\s+)?function\s+(\w+)\s*\((.*?)\)|(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?\(?(.*?)\)?\s*=>',
        "java": r'(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\((.*?)\)',
        "csharp": r'(?:public|private|protected|static|async|\s)+[\w<>\[\]]+\s+(\w+)\s*\((.*?)\)',
    }
    pattern = patterns.get(language, patterns["python"])

    results = []
    for i, line in enumerate(lines, 1):
        match = re.search(pattern, line)
        if match:
            groups = [g for g in match.groups() if g is not None]
            name = groups[0] if groups else "unknown"
            params = groups[1] if len(groups) > 1 else ""
            results.append(f"  L{i}: {name}({params})")

    return "\n".join(results) if results else "No functions found"


@tool(approval_mode="never_require")
def find_aws_dependencies(file_path: str, language: str) -> str:
    """
    Find all AWS SDK dependencies in a source file and map to Azure equivalents.
    Returns a table: AWS Service | SDK Package | Azure Equivalent | Azure SDK
    """
    try:
        content = Path(file_path).read_text(errors="replace")
    except Exception as e:
        return f"ERROR: {e}"

    patterns = AWS_PATTERNS.get(language, [])
    found = []

    for pattern, label in patterns:
        for match in re.finditer(pattern, content, re.MULTILINE):
            service = match.group(1) if match.lastindex else label
            service_lower = service.lower().replace("_", "")
            azure = AWS_TO_AZURE.get(service_lower, ("Unknown", "unknown"))
            found.append({
                "aws_service": service,
                "sdk_import": label.format(service) if "{}" in label else label,
                "azure_equivalent": azure[0],
                "azure_sdk": azure[1],
            })

    if not found:
        return "No AWS SDK dependencies found"

    # Deduplicate
    seen = set()
    unique = []
    for dep in found:
        key = dep["aws_service"]
        if key not in seen:
            seen.add(key)
            unique.append(dep)

    header = "| AWS Service | SDK Import | Azure Equivalent | Azure SDK |"
    separator = "|---|---|---|---|"
    rows = [f"| {d['aws_service']} | {d['sdk_import']} | {d['azure_equivalent']} | {d['azure_sdk']} |" for d in unique]

    return "\n".join([header, separator] + rows)
