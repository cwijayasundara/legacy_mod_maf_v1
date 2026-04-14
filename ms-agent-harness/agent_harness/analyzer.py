"""
Migration Analyzer Agent — Explorer archetype.
Reads AWS Lambda modules, produces dependency maps, complexity scores, and analysis.md.
Does NOT modify source code (read-only).
"""

import os
from pathlib import Path

from .base import create_agent, run_with_retry
from .tools import read_file, search_files, list_directory
from .tools.ast_tools import parse_imports, extract_functions, find_aws_dependencies
from .context.complexity_scorer import score_complexity
from .context.chunker import needs_chunking, chunk_file

PROMPT_PATH = Path(__file__).parent / "prompts" / "analyzer.md"


def _load_prompt() -> str:
    """Load the analyzer system prompt from the markdown file."""
    return PROMPT_PATH.read_text(encoding="utf-8")


def create_analyzer():
    """Create the analyzer agent with read-only tools."""
    return create_agent(
        name="analyzer",
        system_prompt=_load_prompt(),
        tools=[
            read_file,
            search_files,
            list_directory,
            parse_imports,
            extract_functions,
            find_aws_dependencies,
        ],
    )


async def analyze_module(
    module: str, language: str, source_dir: str,
    source_paths: list[str] | tuple = (),
    context_paths: list[str] | tuple = (),
) -> str:
    """Analyze a Lambda module for migration to Azure Functions.

    When source_paths is provided, those files (not a rglob of source_dir)
    are the sole source. context_paths are listed read-only.
    """
    agent = create_analyzer()

    output_dir = Path("migration-analysis") / module
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis_path = output_dir / "analysis.md"

    file_contents: list[str] = []
    if source_paths:
        for spath in source_paths:
            p = Path(spath)
            if not p.is_file():
                continue
            if needs_chunking(p):
                for i, chunk in enumerate(chunk_file(p)):
                    file_contents.append(f"--- {p} (chunk {i + 1}) ---\n{chunk}")
            else:
                file_contents.append(
                    f"--- {p} ---\n{p.read_text(encoding='utf-8', errors='replace')}"
                )
    else:
        src = Path(source_dir)
        for fpath in sorted(src.rglob("*")):
            if fpath.is_file() and not fpath.name.startswith("."):
                if needs_chunking(fpath):
                    for i, chunk in enumerate(chunk_file(fpath)):
                        file_contents.append(f"--- {fpath} (chunk {i + 1}) ---\n{chunk}")
                else:
                    file_contents.append(
                        f"--- {fpath} ---\n{fpath.read_text(encoding='utf-8', errors='replace')}"
                    )

    if context_paths:
        file_contents.append(
            "\n## CONTEXT (read-only — do NOT migrate these files; "
            "treat as an anti-corruption boundary)\n"
        )
        for cpath in context_paths:
            p = Path(cpath)
            if p.is_file():
                file_contents.append(
                    f"--- {p} (read-only) ---\n{p.read_text(encoding='utf-8', errors='replace')}"
                )

    source_listing = "\n\n".join(file_contents)
    complexity = await score_complexity(source_dir, language)

    prompt = (
        f"Analyze the AWS Lambda module '{module}' ({language}) for migration "
        f"to Azure Functions.\n\n"
        f"## Pre-computed Complexity Score\n"
        f"- Overall complexity: {complexity['overall']}\n"
        f"- AWS dependency count: {complexity['aws_dependency_count']}\n"
        f"- Inter-service coupling: {complexity['coupling_score']}\n"
        f"- Trigger count: {complexity['trigger_count']}\n\n"
        f"## Source Files\n\n{source_listing}\n\n"
        f"Write your full analysis to: {analysis_path}\n"
        f"Follow the output format from your system instructions exactly."
    )

    result = await run_with_retry(agent, prompt, max_retries=3)
    analysis_path.write_text(result, encoding="utf-8")
    return str(analysis_path)
