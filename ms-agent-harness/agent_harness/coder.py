"""
Migration Coder Agent — Worker archetype (GENERATOR role).
Performs Lambda -> Azure Functions migration using TDD-first approach.
Writes code and tests but does NOT evaluate its own work.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .base import create_agent, run_with_retry
from .tools import read_file, write_file, search_files, list_directory, apply_patch
from .context.chunker import needs_chunking, chunk_file


def create_coder(repo_root=None, module_path=None):
    """Create the coder agent with read/write tools."""
    return create_agent(
        role="coder",
        tools=[read_file, write_file, search_files, list_directory, apply_patch],
        repo_root=repo_root,
        module_path=module_path,
    )


async def propose_contract(module: str, analysis_path: str) -> str:
    """
    Propose a sprint contract based on the analyzer's output.

    The coder reads the analysis.md and produces a sprint-contract.json
    defining exactly what PASS means for this module's migration.

    Args:
        module: Name of the module being migrated.
        analysis_path: Path to the analysis.md produced by the analyzer.

    Returns:
        Path to the generated sprint-contract.json.
    """
    agent = create_coder()

    output_dir = Path("migration-analysis") / module
    output_dir.mkdir(parents=True, exist_ok=True)
    contract_path = output_dir / "sprint-contract.json"

    # Read the analysis
    analysis_content = Path(analysis_path).read_text(encoding="utf-8")

    # Handle chunking for large analysis files
    if needs_chunking(Path(analysis_path)):
        chunks = chunk_file(Path(analysis_path))
        analysis_content = "\n\n".join(chunks)

    prompt = (
        f"Read the following analysis for module '{module}' and propose a sprint contract.\n\n"
        f"## Analysis\n{analysis_content}\n\n"
        f"Write a sprint contract JSON to: {contract_path}\n"
        f"The contract must include:\n"
        f"- unit_checks: specific behaviors to unit test (function + expected behavior)\n"
        f"- integration_checks: Azure SDK interactions to verify\n"
        f"- contract_checks: API request/response schemas that must match original\n"
        f"- architecture_checks: files required, no AWS imports, Bicep template, coverage minimum\n"
        f"- proposed_by: 'migration-coder'\n"
        f"- proposed_at: '{datetime.now(timezone.utc).isoformat()}'\n\n"
        f"Return ONLY the JSON content."
    )

    result = await run_with_retry(agent, prompt, max_retries=3)

    # Parse and write the contract
    try:
        contract = json.loads(result)
    except json.JSONDecodeError:
        # If the LLM returned markdown-wrapped JSON, extract it
        import re
        json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", result, re.DOTALL)
        if json_match:
            contract = json.loads(json_match.group(1))
        else:
            contract = {"raw_output": result, "parse_error": True}

    contract.setdefault("proposed_by", "migration-coder")
    contract.setdefault("proposed_at", datetime.now(timezone.utc).isoformat())

    contract_path.write_text(
        json.dumps(contract, indent=2), encoding="utf-8"
    )

    return str(contract_path)


async def migrate_module(
    module: str,
    language: str,
    source_dir: str,
    analysis_path: str,
    attempt: int = 1,
    source_paths: list[str] | tuple = (),
    context_paths: list[str] | tuple = (),
    repo_root: str | None = None,
    module_path: str | None = None,
) -> str:
    """
    Perform TDD-first migration of a Lambda module to Azure Functions.

    Args:
        module: Name of the module being migrated.
        language: Programming language (python, node, java, csharp).
        source_dir: Path to the original Lambda source code.
        analysis_path: Path to the analysis.md from the analyzer.
        attempt: Current attempt number (1-3 for self-healing cycle).

    Returns:
        Path to the migrated Azure Function directory.
    """
    agent = create_coder(repo_root=repo_root, module_path=module_path)

    output_base = Path("src/azure-functions") / module
    output_base.mkdir(parents=True, exist_ok=True)
    infra_dir = Path("infrastructure") / module
    infra_dir.mkdir(parents=True, exist_ok=True)

    analysis_dir = Path("migration-analysis") / module

    # Read analysis
    analysis_content = Path(analysis_path).read_text(encoding="utf-8")

    # Read sprint contract if it exists
    contract_path = analysis_dir / "sprint-contract.json"
    contract_content = ""
    if contract_path.exists():
        contract_content = contract_path.read_text(encoding="utf-8")

    # Gather source files to migrate.
    src_blocks: list[str] = []
    targets = [Path(p) for p in source_paths] if source_paths else [
        p for p in Path(source_dir).rglob("*") if p.is_file() and not p.name.startswith(".")
    ]
    for p in targets:
        if not p.is_file():
            continue
        if needs_chunking(p):
            for i, chunk in enumerate(chunk_file(p)):
                src_blocks.append(f"--- {p} (chunk {i + 1}) ---\n{chunk}")
        else:
            src_blocks.append(
                f"--- {p} ---\n{p.read_text(encoding='utf-8', errors='replace')}"
            )

    if context_paths:
        src_blocks.append(
            "\n## CONTEXT (read-only — anti-corruption boundary)\n"
            "You MAY import from these files, but MUST NOT modify or re-create them.\n"
        )
        for cpath in context_paths:
            p = Path(cpath)
            if p.is_file():
                src_blocks.append(
                    f"--- {p} (read-only) ---\n{p.read_text(encoding='utf-8', errors='replace')}"
                )

    source_listing = "\n\n".join(src_blocks)

    # Read failure report if this is a retry attempt
    failure_context = ""
    if attempt > 1:
        failures_path = analysis_dir / "eval-failures.json"
        if failures_path.exists():
            failure_context = (
                f"\n\n## Previous Failure Report (Attempt {attempt - 1})\n"
                f"{failures_path.read_text(encoding='utf-8')}\n"
                f"Apply the self-healing strategy from the failure report."
            )

    prompt = (
        f"Migrate the AWS Lambda module '{module}' ({language}) to Azure Functions.\n"
        f"This is attempt {attempt}/3.\n\n"
        f"## Analysis\n{analysis_content}\n\n"
        f"## Sprint Contract\n{contract_content}\n\n"
        f"## Original Lambda Source\n{source_listing}\n\n"
        f"{failure_context}\n\n"
        f"Follow TDD-first sequence:\n"
        f"1. Write unit tests to {output_base}/tests/\n"
        f"2. Write the Azure Function to {output_base}/\n"
        f"3. Generate Bicep template to {infra_dir}/main.bicep\n\n"
        f"Follow your system instructions for language-specific patterns."
    )

    result = await run_with_retry(agent, prompt, max_retries=3)

    # The agent writes files via tool calls; result is a summary
    summary_path = analysis_dir / "coder-output.md"
    summary_path.write_text(result, encoding="utf-8")

    return str(output_base)
