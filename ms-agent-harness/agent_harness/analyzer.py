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


async def analyze_module(module: str, language: str, source_dir: str) -> str:
    """
    Analyze an AWS Lambda module for migration to Azure Functions.

    Args:
        module: Name of the Lambda module (e.g. 'order-processor').
        language: Programming language (python, node, java, csharp).
        source_dir: Path to the source directory containing the Lambda code.

    Returns:
        Path to the generated analysis.md file.
    """
    agent = create_analyzer()

    # Determine output directory
    output_dir = Path("migration-analysis") / module
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis_path = output_dir / "analysis.md"

    # Build the list of source files, handling large files via chunking
    source_path = Path(source_dir)
    file_contents = []
    for fpath in sorted(source_path.rglob("*")):
        if fpath.is_file() and not fpath.name.startswith("."):
            if needs_chunking(fpath):
                chunks = chunk_file(fpath)
                for i, chunk in enumerate(chunks):
                    file_contents.append(
                        f"--- {fpath} (chunk {i + 1}/{len(chunks)}) ---\n{chunk}"
                    )
            else:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                file_contents.append(f"--- {fpath} ---\n{content}")

    source_listing = "\n\n".join(file_contents)

    # Run complexity scoring independently
    complexity = await score_complexity(source_dir, language)

    # Compose the user prompt
    prompt = (
        f"Analyze the AWS Lambda module '{module}' ({language}) at {source_dir}/ "
        f"for migration to Azure Functions.\n\n"
        f"## Pre-computed Complexity Score\n"
        f"- Overall complexity: {complexity['overall']}\n"
        f"- AWS dependency count: {complexity['aws_dependency_count']}\n"
        f"- Inter-service coupling: {complexity['coupling_score']}\n"
        f"- Trigger count: {complexity['trigger_count']}\n\n"
        f"## Source Files\n\n{source_listing}\n\n"
        f"Write your full analysis to: {analysis_path}\n"
        f"Follow the output format from your system instructions exactly."
    )

    # Execute with retry (handles transient LLM failures)
    result = await run_with_retry(agent, prompt, max_retries=3)

    # Write the analysis output
    analysis_path.write_text(result, encoding="utf-8")

    return str(analysis_path)
