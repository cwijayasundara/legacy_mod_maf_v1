"""
Semantic file chunker.

Splits large source files at function/class boundaries (not arbitrary line splits)
to preserve code intent. Adds overlap between chunks for context continuity.

Based on Azure Legacy Modernization Agents' ChunkedMigrationProcess:
- Files >3000 lines or >150K chars trigger chunking
- Splits at AST-meaningful boundaries (function, class, method definitions)
- Configurable overlap (default 50 lines)
"""

import re
from dataclasses import dataclass

from ..config import load_settings


@dataclass
class Chunk:
    """A semantic chunk of source code."""
    index: int
    start_line: int
    end_line: int
    content: str
    context_summary: str = ""  # Summary of preceding chunks for context


# Boundary patterns per language (function/class/method definitions)
BOUNDARY_PATTERNS = {
    "python": re.compile(r'^(?:class\s+\w|(?:async\s+)?def\s+\w)', re.MULTILINE),
    "node": re.compile(r'^(?:(?:async\s+)?function\s+\w|class\s+\w|(?:const|let)\s+\w+\s*=\s*(?:async\s+)?(?:\(|function))', re.MULTILINE),
    "java": re.compile(r'^\s*(?:public|private|protected|static|\s)*(?:class|interface|(?:[\w<>\[\]]+\s+\w+\s*\())', re.MULTILINE),
    "csharp": re.compile(r'^\s*(?:public|private|protected|static|async|\s)*(?:class|interface|(?:[\w<>\[\]]+\s+\w+\s*\())', re.MULTILINE),
}


def needs_chunking(content: str) -> bool:
    """Check if a file exceeds chunking thresholds."""
    settings = load_settings()
    lines = content.count("\n") + 1
    chars = len(content)
    return lines > settings.chunking.max_lines or chars > settings.chunking.max_chars


def chunk_file(content: str, language: str, target_chunk_lines: int = 500) -> list[Chunk]:
    """
    Split a large source file into semantic chunks.

    Strategy:
    1. Find all function/class boundaries
    2. Group consecutive boundaries into chunks of ~target_chunk_lines
    3. Add overlap_lines from the previous chunk for context

    Returns list of Chunks with content and metadata.
    """
    if not needs_chunking(content):
        return [Chunk(index=0, start_line=1, end_line=content.count("\n") + 1, content=content)]

    settings = load_settings()
    overlap = settings.chunking.overlap_lines
    lines = content.split("\n")
    total_lines = len(lines)

    # Find boundary line numbers
    pattern = BOUNDARY_PATTERNS.get(language, BOUNDARY_PATTERNS["python"])
    boundaries = []
    for i, line in enumerate(lines):
        if pattern.match(line):
            boundaries.append(i)

    # If no boundaries found, fall back to fixed-size chunks
    if not boundaries:
        return _fixed_size_chunks(lines, target_chunk_lines, overlap)

    # Group boundaries into chunks
    chunks = []
    chunk_start = 0

    for i, boundary in enumerate(boundaries):
        # Check if we've accumulated enough lines for a chunk
        lines_so_far = boundary - chunk_start
        if lines_so_far >= target_chunk_lines or i == len(boundaries) - 1:
            # End this chunk at the current boundary (or end of file for last)
            chunk_end = boundaries[i + 1] if i + 1 < len(boundaries) else total_lines

            # Add overlap from previous chunk
            overlap_start = max(0, chunk_start - overlap)

            chunk_content = "\n".join(lines[overlap_start:chunk_end])
            chunks.append(Chunk(
                index=len(chunks),
                start_line=chunk_start + 1,  # 1-indexed
                end_line=chunk_end,
                content=chunk_content,
            ))

            chunk_start = boundary

    # Ensure last chunk captures remaining lines
    if chunk_start < total_lines:
        overlap_start = max(0, chunk_start - overlap)
        chunk_content = "\n".join(lines[overlap_start:])
        if not chunks or chunks[-1].end_line < total_lines:
            chunks.append(Chunk(
                index=len(chunks),
                start_line=chunk_start + 1,
                end_line=total_lines,
                content=chunk_content,
            ))

    return chunks


def _fixed_size_chunks(lines: list[str], target: int, overlap: int) -> list[Chunk]:
    """Fallback: split at fixed line intervals with overlap."""
    chunks = []
    total = len(lines)
    start = 0
    while start < total:
        end = min(start + target, total)
        overlap_start = max(0, start - overlap)
        content = "\n".join(lines[overlap_start:end])
        chunks.append(Chunk(
            index=len(chunks),
            start_line=start + 1,
            end_line=end,
            content=content,
        ))
        start = end
    return chunks
