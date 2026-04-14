from pathlib import Path

from agent_harness.tools.patch_tool import apply_patch


def _write(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8")


def test_single_edit_happy_path(tmp_path):
    f = tmp_path / "a.py"
    _write(f, "hello world\n")
    result = apply_patch([
        {"file": str(f), "old_string": "hello", "new_string": "goodbye"},
    ])
    assert "applied 1 edit" in result
    assert f.read_text(encoding="utf-8") == "goodbye world\n"


def test_batch_multi_file(tmp_path):
    a = tmp_path / "a.py"; b = tmp_path / "b.py"
    _write(a, "alpha\n"); _write(b, "beta\n")
    result = apply_patch([
        {"file": str(a), "old_string": "alpha", "new_string": "AAA"},
        {"file": str(b), "old_string": "beta",  "new_string": "BBB"},
        {"file": str(a), "old_string": "\n",    "new_string": "!\n"},
    ])
    assert "applied 3" in result
    assert a.read_text() == "AAA!\n"
    assert b.read_text() == "BBB\n"


def test_edit_rejected_when_old_string_missing(tmp_path):
    f = tmp_path / "a.py"
    _write(f, "hello world\n")
    result = apply_patch([
        {"file": str(f), "old_string": "hello", "new_string": "goodbye"},
        {"file": str(f), "old_string": "ghost", "new_string": "spirit"},
    ])
    assert result.startswith("ERROR")
    assert "found 0" in result
    assert f.read_text() == "hello world\n"


def test_edit_rejected_when_old_string_duplicated(tmp_path):
    f = tmp_path / "a.py"
    _write(f, "foo foo\n")
    result = apply_patch([
        {"file": str(f), "old_string": "foo", "new_string": "bar"},
    ])
    assert result.startswith("ERROR")
    assert "found 2" in result
    assert f.read_text() == "foo foo\n"


def test_expected_count_greater_than_one(tmp_path):
    f = tmp_path / "a.py"
    _write(f, "x x x\n")
    result = apply_patch([
        {"file": str(f), "old_string": "x", "new_string": "y", "expected_count": 3},
    ])
    assert "applied 1" in result
    assert f.read_text() == "y y y\n"


def test_file_not_found(tmp_path):
    result = apply_patch([
        {"file": str(tmp_path / "ghost.py"), "old_string": "x", "new_string": "y"},
    ])
    assert result.startswith("ERROR")
    assert "file not found" in result


def test_malformed_edit_dict(tmp_path):
    result = apply_patch([{"oops": "missing keys"}])
    assert result.startswith("ERROR")
    assert "malformed" in result
