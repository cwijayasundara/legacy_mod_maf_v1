"""Tests for agents/tools/file_tools.py — pure file I/O, no LLM calls."""

from agent_harness.tools.file_tools import (
    read_file,
    write_file,
    list_directory,
    _python_search,
)


class TestReadFile:
    def test_read_file(self, tmp_dir):
        f = tmp_dir / "hello.txt"
        f.write_text("hello world", encoding="utf-8")
        result = read_file(str(f))
        assert result == "hello world"

    def test_read_file_not_found(self, tmp_dir):
        result = read_file(str(tmp_dir / "nonexistent.txt"))
        assert "ERROR" in result
        assert "not found" in result.lower()


class TestWriteFile:
    def test_write_file(self, tmp_dir):
        target = tmp_dir / "output.txt"
        result = write_file(str(target), "content here")
        assert "Written" in result
        assert target.exists()
        assert target.read_text() == "content here"

    def test_write_file_creates_dirs(self, tmp_dir):
        target = tmp_dir / "a" / "b" / "c" / "deep.txt"
        result = write_file(str(target), "deep content")
        assert "Written" in result
        assert target.exists()
        assert target.read_text() == "deep content"


class TestSearchFiles:
    def test_search_files(self, tmp_dir):
        """Use the Python fallback search directly (no ripgrep dependency)."""
        (tmp_dir / "one.py").write_text("import boto3\nprint('hello')\n")
        (tmp_dir / "two.py").write_text("import os\nprint('world')\n")
        (tmp_dir / "three.txt").write_text("boto3 is great\n")

        result = _python_search("boto3", str(tmp_dir), "**/*")
        assert "boto3" in result
        # Should match in at least one.py and three.txt
        assert "one.py" in result
        assert "three.txt" in result
        # two.py has no boto3
        assert "two.py" not in result


class TestListDirectory:
    def test_list_directory(self, tmp_dir):
        (tmp_dir / "a.py").write_text("")
        (tmp_dir / "b.txt").write_text("")
        sub = tmp_dir / "subdir"
        sub.mkdir()
        (sub / "c.js").write_text("")

        result = list_directory(str(tmp_dir))
        assert "a.py" in result
        assert "b.txt" in result
        assert "subdir" in result

    def test_list_directory_recursive(self, tmp_dir):
        sub = tmp_dir / "nested"
        sub.mkdir()
        (sub / "deep.py").write_text("")

        result = list_directory(str(tmp_dir), recursive=True)
        assert "deep.py" in result

    def test_list_directory_not_a_dir(self, tmp_dir):
        f = tmp_dir / "file.txt"
        f.write_text("")
        result = list_directory(str(f))
        assert "ERROR" in result
