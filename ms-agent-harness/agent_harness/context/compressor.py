"""
Progressive context compressor.

Keeps recent chunks at full detail, compresses older history to save tokens.
Based on Azure Legacy Modernization Agents' 30% compression for older chunks.

Strategy:
- Last 3 chunks: full detail
- Older chunks: compressed to ~30% via extractive summarization
"""

from dataclasses import dataclass


@dataclass
class CompressedContext:
    """Context with full recent history and compressed older history."""
    full_chunks: list[str]      # Last N chunks at full detail
    compressed_history: str      # Older chunks compressed
    total_original_tokens: int
    total_compressed_tokens: int


def compress_history(
    chunk_contents: list[str],
    keep_full: int = 3,
    compression_ratio: float = 0.3,
) -> CompressedContext:
    """
    Compress conversation/chunk history for context window management.

    Args:
        chunk_contents: List of chunk texts in chronological order
        keep_full: Number of recent chunks to keep at full detail (default 3)
        compression_ratio: Target compression for older chunks (default 0.3 = 30%)

    Returns:
        CompressedContext with full recent chunks and compressed older history
    """
    if len(chunk_contents) <= keep_full:
        return CompressedContext(
            full_chunks=chunk_contents,
            compressed_history="",
            total_original_tokens=_estimate_tokens(chunk_contents),
            total_compressed_tokens=_estimate_tokens(chunk_contents),
        )

    # Split into old (compress) and recent (keep full)
    old_chunks = chunk_contents[:-keep_full]
    recent_chunks = chunk_contents[-keep_full:]

    # Compress old chunks via extractive summarization
    compressed = _extractive_compress(old_chunks, compression_ratio)

    original_tokens = _estimate_tokens(chunk_contents)
    compressed_tokens = _estimate_tokens(recent_chunks) + _estimate_tokens([compressed])

    return CompressedContext(
        full_chunks=recent_chunks,
        compressed_history=compressed,
        total_original_tokens=original_tokens,
        total_compressed_tokens=compressed_tokens,
    )


def _extractive_compress(chunks: list[str], ratio: float) -> str:
    """
    Compress chunks by extracting key lines (function signatures, imports, comments).
    Keeps approximately `ratio` of the original content.

    This is a local, fast compression — no LLM call needed.
    For higher-quality compression, the agent can use an LLM summarization tool.
    """
    compressed_parts = []
    for i, chunk in enumerate(chunks):
        lines = chunk.split("\n")
        target_lines = max(5, int(len(lines) * ratio))

        # Priority: function defs, class defs, imports, comments, docstrings
        key_lines = []
        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(kw) for kw in [
                "def ", "async def ", "class ", "import ", "from ",
                "function ", "const ", "let ", "export ",
                "public ", "private ", "protected ",
                "#", "//", "/*", "/**", '"""', "'''",
            ]):
                key_lines.append(line)

        # Fill remaining budget with first lines of each block
        remaining = target_lines - len(key_lines)
        if remaining > 0:
            step = max(1, len(lines) // remaining)
            for j in range(0, len(lines), step):
                if lines[j].strip() and lines[j] not in key_lines:
                    key_lines.append(lines[j])
                    if len(key_lines) >= target_lines:
                        break

        compressed_parts.append(f"--- Chunk {i + 1} (compressed) ---\n" + "\n".join(key_lines[:target_lines]))

    return "\n\n".join(compressed_parts)


def _estimate_tokens(texts: list[str]) -> int:
    """Quick token estimate: chars / 3.0"""
    return int(sum(len(t) for t in texts) / 3.0)
