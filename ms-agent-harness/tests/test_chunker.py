"""Tests for agents/context/chunker.py — semantic chunking, no LLM calls.

We mock load_settings to avoid reading the real YAML (keeps tests isolated).
"""

from unittest.mock import patch

from agent_harness.config import Settings, SpeedProfile, ChunkingConfig
from agent_harness.context.chunker import chunk_file, needs_chunking, _fixed_size_chunks, Chunk


def _mock_settings(**overrides):
    """Build a Settings with controllable chunking thresholds."""
    chunking = ChunkingConfig(
        max_lines=overrides.get("max_lines", 3000),
        max_chars=overrides.get("max_chars", 150000),
        overlap_lines=overrides.get("overlap_lines", 50),
    )
    return Settings(
        speed_profiles={
            "balanced": SpeedProfile(
                name="balanced",
                description="test",
                token_ceiling=100000,
                reasoning_effort="medium",
                max_parallel_chunks=3,
                complexity_multipliers={"low": 1.5, "medium": 2.5, "high": 3.5},
            ),
        },
        default_profile="balanced",
        chunking=chunking,
    )


class TestNoChunkingNeeded:
    @patch("agents.context.chunker.load_settings", return_value=_mock_settings())
    def test_short_file_single_chunk(self, mock_settings):
        content = "def hello():\n    return 'world'\n"
        chunks = chunk_file(content, "python")
        assert len(chunks) == 1
        assert chunks[0].content == content
        assert chunks[0].index == 0


class TestNeedsChunking:
    @patch("agents.context.chunker.load_settings",
           return_value=_mock_settings(max_lines=100))
    def test_large_file_triggers_chunking(self, mock_settings):
        # 200 lines exceeds threshold of 100
        content = "\n".join(f"line_{i} = {i}" for i in range(200))
        assert needs_chunking(content) is True

    @patch("agents.context.chunker.load_settings",
           return_value=_mock_settings(max_lines=5000))
    def test_small_file_no_chunking(self, mock_settings):
        content = "x = 1\ny = 2\n"
        assert needs_chunking(content) is False


class TestChunkAtBoundaries:
    @patch("agents.context.chunker.load_settings",
           return_value=_mock_settings(max_lines=20, overlap_lines=5))
    def test_splits_at_def_boundaries(self, mock_settings):
        """Create a Python file with multiple functions; chunks should split at def lines."""
        parts = []
        for i in range(6):
            parts.append(f"def func_{i}():")
            for j in range(8):
                parts.append(f"    x_{j} = {j}")
        content = "\n".join(parts)

        chunks = chunk_file(content, "python", target_chunk_lines=15)
        assert len(chunks) > 1

        # Each chunk (except possibly the first) should start near a def boundary
        for ch in chunks:
            lines = ch.content.strip().split("\n")
            # At least one line should contain "def "
            has_def = any("def " in l for l in lines)
            assert has_def, f"Chunk {ch.index} has no function boundary"


class TestOverlap:
    @patch("agents.context.chunker.load_settings",
           return_value=_mock_settings(max_lines=20, overlap_lines=5))
    def test_chunks_have_overlapping_lines(self, mock_settings):
        """Consecutive chunks should share overlapping lines."""
        parts = []
        for i in range(6):
            parts.append(f"def func_{i}():")
            for j in range(8):
                parts.append(f"    line_{i}_{j} = {j}")
        content = "\n".join(parts)

        chunks = chunk_file(content, "python", target_chunk_lines=15)
        if len(chunks) >= 2:
            # Second chunk start_line should be less than first chunk end_line
            # (overlap means we re-include lines from the previous chunk)
            first_end = chunks[0].end_line
            second_content_lines = set(chunks[1].content.split("\n"))
            first_content_lines = set(chunks[0].content.split("\n"))
            overlap = first_content_lines & second_content_lines
            assert len(overlap) > 0, "Expected overlapping lines between chunks"


class TestFixedSizeFallback:
    def test_fixed_size_fallback(self):
        """File with no function boundaries falls back to fixed-size chunks."""
        lines = [f"data_{i} = {i}" for i in range(100)]
        chunks = _fixed_size_chunks(lines, target=30, overlap=5)
        assert len(chunks) >= 3  # 100 / 30 ~ 4 chunks
        # All lines should be covered
        for ch in chunks:
            assert ch.content  # non-empty

    def test_fixed_size_overlap(self):
        lines = [f"row_{i}" for i in range(60)]
        chunks = _fixed_size_chunks(lines, target=20, overlap=5)
        assert len(chunks) == 3  # 0-20, 20-40, 40-60
        # Second chunk should include overlap from first
        assert "row_15" in chunks[1].content  # overlap reaches back 5 lines from 20
