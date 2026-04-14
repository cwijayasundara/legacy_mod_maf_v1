from pathlib import Path
from unittest.mock import patch

from agent_harness.base import load_prompt


def test_back_compat_no_kwargs(tmp_path, monkeypatch):
    stub = tmp_path / "prompts"
    stub.mkdir()
    (stub / "coder.md").write_text("STUB CODER PROMPT\n", encoding="utf-8")
    with patch("agent_harness.base.PROMPTS_DIR", stub), \
         patch("agent_harness.base.DISCOVERY_PROMPTS_DIR", tmp_path / "empty"):
        out = load_prompt("coder")
    assert "STUB CODER PROMPT" in out
    assert "## Repo context (AGENTS.md)" not in out
    assert "## Module context (AGENTS.md)" not in out


def test_repo_only(tmp_path):
    stub = tmp_path / "prompts"; stub.mkdir()
    (stub / "coder.md").write_text("STUB\n", encoding="utf-8")
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "AGENTS.md").write_text("REPO-LEVEL-GUIDANCE\n", encoding="utf-8")
    with patch("agent_harness.base.PROMPTS_DIR", stub), \
         patch("agent_harness.base.DISCOVERY_PROMPTS_DIR", tmp_path / "empty"):
        out = load_prompt("coder", repo_root=repo)
    assert "## Repo context (AGENTS.md)" in out
    assert "REPO-LEVEL-GUIDANCE" in out
    assert "## Module context (AGENTS.md)" not in out


def test_module_only(tmp_path):
    stub = tmp_path / "prompts"; stub.mkdir()
    (stub / "coder.md").write_text("STUB\n", encoding="utf-8")
    module = tmp_path / "mod"; module.mkdir()
    (module / "AGENTS.md").write_text("MODULE-GUIDANCE\n", encoding="utf-8")
    with patch("agent_harness.base.PROMPTS_DIR", stub), \
         patch("agent_harness.base.DISCOVERY_PROMPTS_DIR", tmp_path / "empty"):
        out = load_prompt("coder", module_path=module)
    assert "## Repo context (AGENTS.md)" not in out
    assert "## Module context (AGENTS.md)" in out
    assert "MODULE-GUIDANCE" in out


def test_both_present_order_correct(tmp_path):
    stub = tmp_path / "prompts"; stub.mkdir()
    (stub / "coder.md").write_text("STUB\n", encoding="utf-8")
    repo = tmp_path / "repo"; repo.mkdir()
    module = repo / "mod"; module.mkdir()
    (repo / "AGENTS.md").write_text("REPO-TEXT\n", encoding="utf-8")
    (module / "AGENTS.md").write_text("MODULE-TEXT\n", encoding="utf-8")
    with patch("agent_harness.base.PROMPTS_DIR", stub), \
         patch("agent_harness.base.DISCOVERY_PROMPTS_DIR", tmp_path / "empty"):
        out = load_prompt("coder", repo_root=repo, module_path=module)
    repo_idx = out.index("## Repo context (AGENTS.md)")
    mod_idx = out.index("## Module context (AGENTS.md)")
    assert repo_idx < mod_idx
    assert "REPO-TEXT" in out
    assert "MODULE-TEXT" in out


def test_missing_agents_md_silently_skipped(tmp_path):
    stub = tmp_path / "prompts"; stub.mkdir()
    (stub / "coder.md").write_text("STUB\n", encoding="utf-8")
    repo = tmp_path / "repo"; repo.mkdir()
    with patch("agent_harness.base.PROMPTS_DIR", stub), \
         patch("agent_harness.base.DISCOVERY_PROMPTS_DIR", tmp_path / "empty"):
        out = load_prompt("coder", repo_root=repo, module_path=repo / "nope")
    assert "## Repo context" not in out
    assert "## Module context" not in out
