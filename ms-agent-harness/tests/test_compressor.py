"""Tests for agents/context/compressor.py — progressive compression, no LLM calls."""

from agent_harness.context.compressor import compress_history, CompressedContext


class TestNoCompressionNeeded:
    def test_three_or_fewer_chunks_returns_all_full(self):
        chunks = ["chunk one content", "chunk two content", "chunk three"]
        result = compress_history(chunks)
        assert len(result.full_chunks) == 3
        assert result.compressed_history == ""
        assert result.full_chunks == chunks

    def test_single_chunk(self):
        result = compress_history(["only one"])
        assert len(result.full_chunks) == 1
        assert result.compressed_history == ""

    def test_empty_input(self):
        result = compress_history([])
        assert len(result.full_chunks) == 0
        assert result.compressed_history == ""


class TestCompressesOldChunks:
    def test_six_chunks_splits_correctly(self):
        """6 chunks with keep_full=3 -> last 3 full, first 3 compressed."""
        chunks = [f"chunk {i} content with some text" for i in range(6)]
        result = compress_history(chunks, keep_full=3)

        # Last 3 kept at full detail
        assert result.full_chunks == chunks[3:]
        assert len(result.full_chunks) == 3

        # Compressed history is non-empty
        assert len(result.compressed_history) > 0
        assert "compressed" in result.compressed_history.lower()

    def test_compressed_is_smaller(self):
        """Compressed output should be smaller than original old chunks."""
        old = ["x" * 1000 + "\ndef func():\n    pass\n" for _ in range(5)]
        recent = ["recent chunk"]
        all_chunks = old + recent
        result = compress_history(all_chunks, keep_full=1)
        # The compressed history should be shorter than the 5 old chunks combined
        original_old_len = sum(len(c) for c in old)
        assert len(result.compressed_history) < original_old_len

    def test_token_counts(self):
        chunks = [f"content chunk {i} " * 20 for i in range(6)]
        result = compress_history(chunks, keep_full=3)
        assert result.total_compressed_tokens < result.total_original_tokens


class TestCompressionPreservesKeyLines:
    def test_function_defs_survive(self):
        """Function definitions should be preserved in compressed output."""
        chunks = [
            "import os\nimport sys\n\ndef important_function(x):\n    return x * 2\n\n" + ("filler = 1\n" * 50),
            "from pathlib import Path\n\nclass MyClass:\n    def method(self):\n        pass\n\n" + ("data = 2\n" * 50),
            "def another_func():\n    pass\n" + ("more = 3\n" * 50),
        ]
        recent = ["recent chunk content"]
        all_chunks = chunks + recent
        result = compress_history(all_chunks, keep_full=1)

        compressed = result.compressed_history
        assert "def important_function" in compressed
        assert "import os" in compressed
        assert "class MyClass" in compressed or "def method" in compressed

    def test_imports_survive(self):
        chunks = [
            "import boto3\nfrom datetime import datetime\n" + ("x = 1\n" * 100),
        ]
        recent = ["recent"]
        all_chunks = chunks + recent
        result = compress_history(all_chunks, keep_full=1)
        assert "import boto3" in result.compressed_history
        assert "from datetime" in result.compressed_history
