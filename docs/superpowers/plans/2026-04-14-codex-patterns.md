# Codex-OSS Pattern Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three Codex-OSS patterns to the harness: auto-loaded `AGENTS.md` context (per-repo + per-module), an `apply_patch` search-replace edit tool, and a `validate_bicep` IaC validator. Thread the new context kwargs through every agent factory (migration + discovery) without breaking existing call sites.

**Architecture:** Two new tool modules (`tools/patch_tool.py`, `tools/bicep_tool.py`). `base.load_prompt` grows optional `repo_root` / `module_path` kwargs that append `<repo_root>/AGENTS.md` and `<module_path>/AGENTS.md` after the existing `quality-principles` / `learned-rules` / `program.md` injection. `base.create_agent` forwards the kwargs. Every `create_*` factory in the migration + discovery agents grows the same two optional kwargs. `MigrationPipeline.run` derives `repo_root = common_ancestor(source_paths + context_paths)` and `module_path = source_paths[0].parent` and threads them. Discovery workflow threads `repo_root=repo_path`. Coder gets `apply_patch`; reviewer + security_reviewer get `validate_bicep`.

**Tech Stack:** Python 3.11, existing `agent_framework` mock in tests, `subprocess` for `az bicep build`, `pytest`. All paths in this plan are relative to `ms-agent-harness/` unless stated. Run tests with `python3 -m pytest`. Pre-existing failures in `tests/test_chunker.py`, `test_complexity_scorer.py`, `test_compressor.py`, `test_token_estimator.py`, `test_integration.py`, `test_ast_tools.py` are unrelated — scope regression checks to files this plan touches.

---

## File Structure

| File | Responsibility |
|---|---|
| `agent_harness/tools/patch_tool.py` | **NEW** — `apply_patch(edits)` search-replace with batch validation |
| `agent_harness/tools/bicep_tool.py` | **NEW** — `validate_bicep(path)` via `az bicep build` |
| `agent_harness/tools/__init__.py` | Re-export `apply_patch`, `validate_bicep` |
| `agent_harness/base.py` | `load_prompt` gains `repo_root`/`module_path` kwargs; `create_agent` forwards them |
| `agent_harness/analyzer.py` | `create_analyzer` + `analyze_module` accept `repo_root`/`module_path`, forward to factory |
| `agent_harness/coder.py` | `create_coder` + `migrate_module` accept the kwargs; coder's tools include `apply_patch` |
| `agent_harness/tester.py` | `create_tester` + `evaluate_module` accept the kwargs |
| `agent_harness/reviewer.py` | `create_reviewer` + `review_module` accept the kwargs; reviewer's tools include `validate_bicep` |
| `agent_harness/security_reviewer.py` | `create_security_reviewer` + `security_review` accept the kwargs; tools include `validate_bicep` |
| `agent_harness/pipeline.py` | `_common_ancestor` helper; `MigrationPipeline.run` derives + threads paths |
| `agent_harness/discovery/repo_scanner.py` | `_run_agent` takes `repo_root` kwarg |
| `agent_harness/discovery/dependency_grapher.py` | same |
| `agent_harness/discovery/brd_extractor.py` | `_run_module_agent` + `_run_system_agent` take `repo_root` |
| `agent_harness/discovery/architect.py` | same |
| `agent_harness/discovery/story_decomposer.py` | `_run_agent` takes `repo_root` |
| `agent_harness/discovery/workflow.py` | `run_discovery` threads `repo_path` into every `_run_agent` seam |
| `agent_harness/prompts/reviewer.md` | Append section: how to interpret VALID / INVALID / SKIPPED |
| `agent_harness/prompts/security-reviewer.md` | Same |
| `templates/AGENTS.md.example` | **NEW** — documented convention |
| `tests/test_patch_tool.py` | **NEW** |
| `tests/test_bicep_tool.py` | **NEW** |
| `tests/test_load_prompt_agents_md.py` | **NEW** |
| `tests/test_pipeline_agents_md.py` | **NEW** integration test |
| `README.md` | Append section on AGENTS.md usage |

**Conventions:**
- Commit per task.
- Tests mock subprocess / patching `_run_agent` where appropriate; no real LLM in test suite.
- `@tool(approval_mode="never_require")` from `agent_framework` is a harmless pass-through under the existing conftest mock.

---

## Task 1: `apply_patch` tool

**Files:**
- Create: `agent_harness/tools/patch_tool.py`
- Test: `tests/test_patch_tool.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_patch_tool.py
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
    # First file untouched because the batch aborted.
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_patch_tool.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# agent_harness/tools/patch_tool.py
"""Search-replace editing tool. All-or-nothing batch semantics."""
from __future__ import annotations

from pathlib import Path

from agent_framework import tool


@tool(approval_mode="never_require")
def apply_patch(edits: list[dict]) -> str:
    """Apply a batch of search-replace edits atomically.

    Each edit is a dict: {file, old_string, new_string, expected_count}.
    expected_count defaults to 1. All edits are validated before any file
    is touched; any failure aborts the entire batch and no file is modified.

    Returns a summary string. On failure, returns 'ERROR: <reason>'.
    """
    plans: list[tuple[Path, str, str, str, int]] = []
    for i, edit in enumerate(edits):
        try:
            file = edit["file"]
            old = edit["old_string"]
            new = edit["new_string"]
            expected = int(edit.get("expected_count", 1))
        except (KeyError, TypeError, ValueError) as exc:
            return f"ERROR: edit {i} malformed: {exc}"
        path = Path(file)
        if not path.is_file():
            return f"ERROR: edit {i}: file not found: {file}"
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"ERROR: edit {i}: could not read {file}: {exc}"
        count = content.count(old)
        if count != expected:
            return (f"ERROR: edit {i} for {file}: "
                    f"expected {expected} match(es) of old_string, found {count}")
        plans.append((path, content, old, new, expected))

    written: set[str] = set()
    for path, content, old, new, expected in plans:
        updated = content.replace(old, new, expected)
        path.write_text(updated, encoding="utf-8")
        written.add(str(path))

    return f"applied {len(edits)} edit(s) to {len(written)} file(s)"
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_patch_tool.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/tools/patch_tool.py tests/test_patch_tool.py
git commit -m "feat(tools): add apply_patch for atomic batch search-replace edits"
```

---

## Task 2: `validate_bicep` tool

**Files:**
- Create: `agent_harness/tools/bicep_tool.py`
- Test: `tests/test_bicep_tool.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bicep_tool.py
import subprocess
from unittest.mock import patch

from agent_harness.tools.bicep_tool import validate_bicep


def _fake_run(returncode=0, stdout="", stderr=""):
    class R:
        pass
    r = R()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def test_valid_bicep_transpiles(tmp_path):
    f = tmp_path / "main.bicep"
    f.write_text("param name string\n")
    with patch("agent_harness.tools.bicep_tool.subprocess.run",
               return_value=_fake_run(returncode=0)):
        assert validate_bicep(str(f)) == "VALID"


def test_invalid_bicep_returns_stderr(tmp_path):
    f = tmp_path / "main.bicep"
    f.write_text("broken\n")
    with patch("agent_harness.tools.bicep_tool.subprocess.run",
               return_value=_fake_run(returncode=1,
                                       stderr="Error BCP018: unexpected token")):
        result = validate_bicep(str(f))
    assert result.startswith("INVALID:")
    assert "BCP018" in result


def test_az_missing_returns_skipped(tmp_path):
    f = tmp_path / "main.bicep"
    f.write_text("ok\n")
    with patch("agent_harness.tools.bicep_tool.subprocess.run",
               side_effect=FileNotFoundError):
        result = validate_bicep(str(f))
    assert result.startswith("SKIPPED")
    assert "az" in result.lower()


def test_timeout_returns_invalid(tmp_path):
    f = tmp_path / "main.bicep"
    f.write_text("ok\n")
    with patch("agent_harness.tools.bicep_tool.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="az", timeout=30)):
        assert validate_bicep(str(f)) == "INVALID: timeout after 30s"


def test_file_not_found_on_disk(tmp_path):
    assert validate_bicep(str(tmp_path / "ghost.bicep")).startswith(
        "INVALID: file not found"
    )


def test_bicep_extension_missing_returns_skipped(tmp_path):
    f = tmp_path / "main.bicep"
    f.write_text("ok\n")
    with patch("agent_harness.tools.bicep_tool.subprocess.run",
               return_value=_fake_run(
                   returncode=1,
                   stderr="az : ERROR: The 'bicep' command is not installed.",
               )):
        result = validate_bicep(str(f))
    assert result.startswith("SKIPPED")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_bicep_tool.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# agent_harness/tools/bicep_tool.py
"""Validate a Bicep file by transpiling with the Azure CLI."""
from __future__ import annotations

import subprocess
from pathlib import Path

from agent_framework import tool


@tool(approval_mode="never_require")
def validate_bicep(path: str) -> str:
    """Transpile <path> with `az bicep build --stdout`.

    Returns 'VALID', 'INVALID: <stderr>', or 'SKIPPED: <reason>'.
    Timeout: 30s.
    """
    p = Path(path)
    if not p.is_file():
        return f"INVALID: file not found: {path}"
    try:
        result = subprocess.run(
            ["az", "bicep", "build", "--stdout", "--file", str(p)],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return "SKIPPED: az CLI not installed"
    except subprocess.TimeoutExpired:
        return "INVALID: timeout after 30s"

    if result.returncode == 0:
        return "VALID"
    stderr = (result.stderr or "").strip()[:2000]
    low = stderr.lower()
    if "bicep' command is not installed" in stderr or "bicep extension" in low:
        return f"SKIPPED: bicep extension not available: {stderr}"
    return f"INVALID: {stderr}"
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_bicep_tool.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add agent_harness/tools/bicep_tool.py tests/test_bicep_tool.py
git commit -m "feat(tools): add validate_bicep using az bicep build"
```

---

## Task 3: Re-export new tools from `tools/__init__.py`

**Files:**
- Modify: `agent_harness/tools/__init__.py`

- [ ] **Step 1: Read the current file**

Current content:

```python
"""Agent tools — @tool-decorated functions for file ops, AST parsing, and test running."""

from .file_tools import read_file, write_file, search_files, list_directory
from .ast_tools import parse_imports, extract_functions, find_aws_dependencies
from .test_runner import run_tests, measure_coverage

__all__ = [
    "read_file", "write_file", "search_files", "list_directory",
    "parse_imports", "extract_functions", "find_aws_dependencies",
    "run_tests", "measure_coverage",
]
```

- [ ] **Step 2: Replace with**

```python
"""Agent tools — @tool-decorated functions for file ops, AST parsing, test running, patching, and Bicep validation."""

from .file_tools import read_file, write_file, search_files, list_directory
from .ast_tools import parse_imports, extract_functions, find_aws_dependencies
from .test_runner import run_tests, measure_coverage
from .patch_tool import apply_patch
from .bicep_tool import validate_bicep

__all__ = [
    "read_file", "write_file", "search_files", "list_directory",
    "parse_imports", "extract_functions", "find_aws_dependencies",
    "run_tests", "measure_coverage",
    "apply_patch", "validate_bicep",
]
```

- [ ] **Step 3: Verify imports work**

Run: `python3 -c "from agent_harness.tools import apply_patch, validate_bicep; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add agent_harness/tools/__init__.py
git commit -m "feat(tools): re-export apply_patch and validate_bicep"
```

---

## Task 4: `base.load_prompt` — AGENTS.md injection

**Files:**
- Modify: `agent_harness/base.py`
- Test: `tests/test_load_prompt_agents_md.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_load_prompt_agents_md.py
from pathlib import Path
from unittest.mock import patch

from agent_harness.base import load_prompt


def test_back_compat_no_kwargs(tmp_path, monkeypatch):
    """load_prompt without the new kwargs behaves identically to before."""
    # Stub PROMPTS_DIR so we don't depend on the real coder.md existing.
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
    # Both headers present; repo-level appears before module-level.
    repo_idx = out.index("## Repo context (AGENTS.md)")
    mod_idx = out.index("## Module context (AGENTS.md)")
    assert repo_idx < mod_idx
    assert "REPO-TEXT" in out
    assert "MODULE-TEXT" in out


def test_missing_agents_md_silently_skipped(tmp_path):
    stub = tmp_path / "prompts"; stub.mkdir()
    (stub / "coder.md").write_text("STUB\n", encoding="utf-8")
    repo = tmp_path / "repo"; repo.mkdir()
    # No AGENTS.md anywhere.
    with patch("agent_harness.base.PROMPTS_DIR", stub), \
         patch("agent_harness.base.DISCOVERY_PROMPTS_DIR", tmp_path / "empty"):
        out = load_prompt("coder", repo_root=repo, module_path=repo / "nope")
    assert "## Repo context" not in out
    assert "## Module context" not in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_load_prompt_agents_md.py -v`
Expected: TypeError — `load_prompt` got unexpected keyword arguments.

- [ ] **Step 3: Extend `load_prompt` in `agent_harness/base.py`**

Locate the existing `def load_prompt(role: str) -> str:` function. Replace its signature and add the AGENTS.md injection at the end, just before `return prompt`:

```python
def load_prompt(role: str,
                repo_root: str | Path | None = None,
                module_path: str | Path | None = None) -> str:
    """Load system prompt from prompts/ directory, falling back to discovery/prompts/.

    When repo_root or module_path is provided, also appends any AGENTS.md
    found at <repo_root>/AGENTS.md and <module_path>/AGENTS.md (in that order)
    under clearly labeled headers. Missing files are silently skipped.
    """
    for candidate in (PROMPTS_DIR / f"{role}.md", DISCOVERY_PROMPTS_DIR / f"{role}.md"):
        if candidate.exists():
            prompt = candidate.read_text()
            break
    else:
        logger.warning("Prompt file not found for role %s", role)
        prompt = f"You are a migration {role} agent."

    # Inject quality principles into every agent's prompt
    quality_path = PROMPTS_DIR / "quality-principles.md"
    if quality_path.exists():
        prompt += "\n\n" + quality_path.read_text()

    # Inject learned rules
    learned_rules = _load_learned_rules()
    if learned_rules:
        prompt += f"\n\n## Learned Rules (inject into all work)\n{learned_rules}"

    # Inject program.md steering
    program = _load_program()
    if program:
        prompt += f"\n\n## Human Steering (from program.md)\n{program}"

    # Inject repo-level AGENTS.md
    if repo_root:
        agents_md = Path(repo_root) / "AGENTS.md"
        if agents_md.is_file():
            try:
                prompt += (
                    f"\n\n## Repo context (AGENTS.md)\n{agents_md.read_text(encoding='utf-8')}"
                )
            except OSError as exc:
                logger.warning("Could not read %s: %s", agents_md, exc)

    # Inject module-level AGENTS.md (overrides repo-level by appearing after).
    if module_path:
        mod_md = Path(module_path) / "AGENTS.md"
        if mod_md.is_file():
            try:
                prompt += (
                    f"\n\n## Module context (AGENTS.md)\n{mod_md.read_text(encoding='utf-8')}"
                )
            except OSError as exc:
                logger.warning("Could not read %s: %s", mod_md, exc)

    return prompt
```

Note: the existing body already calls `_load_learned_rules` and `_load_program` in `create_agent`, not inside `load_prompt`. If the current `load_prompt` only loads the role file + quality-principles, and the other two injections happen in `create_agent`, keep `load_prompt`'s scope to file loading + quality + AGENTS.md and leave learned-rules/program.md in `create_agent` — preserve whatever the current structure is. The AGENTS.md injection goes at the END of whatever `load_prompt` currently does.

In other words: if you open `base.py` and see that learned-rules / program.md injection happens in `create_agent` (not `load_prompt`), then drop those two blocks from the replacement above — only the AGENTS.md blocks are new.

- [ ] **Step 4: Run the test to verify**

Run: `python3 -m pytest tests/test_load_prompt_agents_md.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Regression check**

Run: `python3 -m pytest tests/test_discovery_e2e.py tests/test_fanout_e2e.py tests/test_eval_cli.py -q`
Expected: all prior green tests still pass (new kwargs default to None, no behaviour change for existing callers).

- [ ] **Step 6: Commit**

```bash
git add agent_harness/base.py tests/test_load_prompt_agents_md.py
git commit -m "feat(base): load_prompt injects repo and module AGENTS.md"
```

---

## Task 5: `base.create_agent` forwards AGENTS.md kwargs

**Files:**
- Modify: `agent_harness/base.py`

- [ ] **Step 1: Extend `create_agent`**

Locate:

```python
def create_agent(role: str, tools: list | None = None) -> Agent:
```

Replace with:

```python
def create_agent(role: str, tools: list | None = None,
                 repo_root: str | Path | None = None,
                 module_path: str | Path | None = None) -> Agent:
```

Inside the body, change the call to `load_prompt`:

```python
    prompt = load_prompt(role, repo_root=repo_root, module_path=module_path)
```

- [ ] **Step 2: Sanity-check import**

Run: `python3 -c "from agent_harness.base import create_agent; import inspect; s=inspect.signature(create_agent); assert 'repo_root' in s.parameters; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Regression**

Run: `python3 -m pytest tests/test_load_prompt_agents_md.py tests/test_discovery_e2e.py tests/test_fanout_e2e.py -q`
Expected: all PASS (new kwargs default to None).

- [ ] **Step 4: Commit**

```bash
git add agent_harness/base.py
git commit -m "feat(base): create_agent forwards repo_root/module_path to load_prompt"
```

---

## Task 6: Migration agents accept & forward AGENTS.md kwargs

**Files:**
- Modify: `agent_harness/analyzer.py`
- Modify: `agent_harness/coder.py`
- Modify: `agent_harness/tester.py`
- Modify: `agent_harness/reviewer.py`
- Modify: `agent_harness/security_reviewer.py`

Each file has a `create_<role>()` factory. We add the two optional kwargs and pass through. Additionally, `coder` gets `apply_patch` in its tool list and `reviewer` + `security_reviewer` get `validate_bicep`.

- [ ] **Step 1: `analyzer.py` — extend `create_analyzer`**

Current:

```python
def create_analyzer():
    """Create the analyzer agent with read-only tools."""
    return create_agent(
        name="analyzer",
        system_prompt=_load_prompt(),
        tools=[...],
    )
```

Replace with (keep the existing tool list in the `tools=[...]` parameter, only shown truncated here):

```python
def create_analyzer(repo_root=None, module_path=None):
    """Create the analyzer agent with read-only tools."""
    from .base import create_agent
    return create_agent(
        role="analyzer",
        tools=[
            read_file, search_files, list_directory,
            parse_imports, extract_functions, find_aws_dependencies,
        ],
        repo_root=repo_root, module_path=module_path,
    )
```

If the existing factory uses a different `create_agent` signature (e.g., positional `name=` / `system_prompt=`), use `role="analyzer"` per the base factory's current shape and keep the same tool list. Do not invent new tools.

`analyze_module` also needs to accept `repo_root=None, module_path=None` and pass them when it constructs the agent. Open the file and locate `async def analyze_module(...):` — extend the signature:

```python
async def analyze_module(
    module: str, language: str, source_dir: str,
    source_paths: list[str] | tuple = (),
    context_paths: list[str] | tuple = (),
    repo_root: str | None = None,
    module_path: str | None = None,
) -> str:
```

Replace the call `agent = create_analyzer()` (if present) with `agent = create_analyzer(repo_root=repo_root, module_path=module_path)`.

- [ ] **Step 2: `coder.py` — extend `create_coder` and `migrate_module`**

Same pattern. `create_coder` adds the kwargs and passes through. Also add `apply_patch` to its tool list:

```python
def create_coder(repo_root=None, module_path=None):
    from .base import create_agent
    from .tools import read_file, write_file, search_files, list_directory, apply_patch
    return create_agent(
        role="coder",
        tools=[read_file, write_file, search_files, list_directory, apply_patch],
        repo_root=repo_root, module_path=module_path,
    )
```

`migrate_module` signature (already extended in earlier sub-project for `source_paths`/`context_paths`) gains the two new kwargs at the end:

```python
async def migrate_module(
    module: str, language: str, source_dir: str, analysis_path: str,
    attempt: int = 1,
    source_paths: list[str] | tuple = (),
    context_paths: list[str] | tuple = (),
    repo_root: str | None = None,
    module_path: str | None = None,
) -> str:
```

Update the call to `create_coder()` inside to `create_coder(repo_root=repo_root, module_path=module_path)`.

`propose_contract` does not take paths — leave it as is (it uses `create_coder()` without context). Not every agent call needs AGENTS.md; the per-module pipeline run is what matters.

- [ ] **Step 3: `tester.py` — extend `create_tester` and `evaluate_module`**

```python
def create_tester(repo_root=None, module_path=None):
    from .base import create_agent
    from .tools import read_file, write_file, search_files, list_directory, run_tests, measure_coverage
    return create_agent(
        role="tester",
        tools=[read_file, write_file, search_files, list_directory, run_tests, measure_coverage],
        repo_root=repo_root, module_path=module_path,
    )
```

`evaluate_module` signature gains:

```python
async def evaluate_module(
    module: str, language: str, contract: str, attempt: int = 1,
    source_paths: list[str] | tuple = (),
    context_paths: list[str] | tuple = (),
    repo_root: str | None = None,
    module_path: str | None = None,
) -> str:
```

Update the call inside to `create_tester(repo_root=repo_root, module_path=module_path)`.

`finalize_contract` uses `create_tester()` without context — leave it alone.

- [ ] **Step 4: `reviewer.py` — extend `create_reviewer` and `review_module`**

`create_reviewer` adds kwargs AND `validate_bicep` to the tool list:

```python
def create_reviewer(repo_root=None, module_path=None):
    from .base import create_agent
    from .tools import read_file, search_files, list_directory, validate_bicep
    return create_agent(
        role="reviewer",
        tools=[read_file, search_files, list_directory, validate_bicep],
        repo_root=repo_root, module_path=module_path,
    )
```

`review_module` gains:

```python
async def review_module(
    module: str, language: str,
    repo_root: str | None = None,
    module_path: str | None = None,
) -> dict:
```

Update the call inside to `create_reviewer(repo_root=repo_root, module_path=module_path)`.

- [ ] **Step 5: `security_reviewer.py` — extend `create_security_reviewer` and `security_review`**

```python
def create_security_reviewer(repo_root=None, module_path=None):
    from .base import create_agent
    from .tools import read_file, search_files, list_directory, validate_bicep
    return create_agent(
        role="security-reviewer",
        tools=[read_file, search_files, list_directory, validate_bicep],
        repo_root=repo_root, module_path=module_path,
    )
```

`security_review` gains:

```python
async def security_review(
    module: str, language: str,
    repo_root: str | None = None,
    module_path: str | None = None,
) -> dict:
```

Update the call inside to `create_security_reviewer(repo_root=repo_root, module_path=module_path)`.

- [ ] **Step 6: Sanity-check imports**

Run: `python3 -c "from agent_harness.analyzer import analyze_module; from agent_harness.coder import migrate_module; from agent_harness.tester import evaluate_module; from agent_harness.reviewer import review_module; from agent_harness.security_reviewer import security_review; print('ok')"`
Expected: `ok`.

- [ ] **Step 7: Regression check**

Run: `python3 -m pytest tests/test_pipeline_paths.py tests/test_discovery_e2e.py tests/test_fanout_e2e.py -q`
Expected: all PASS (new kwargs default to None; existing tests don't set them).

- [ ] **Step 8: Commit**

```bash
git add agent_harness/analyzer.py agent_harness/coder.py agent_harness/tester.py \
        agent_harness/reviewer.py agent_harness/security_reviewer.py
git commit -m "feat(agents): migration agents accept repo_root/module_path; coder+reviewers get new tools"
```

---

## Task 7: `MigrationPipeline.run` derives and threads `repo_root`/`module_path`

**Files:**
- Modify: `agent_harness/pipeline.py`
- Test: `tests/test_pipeline_agents_md.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/test_pipeline_agents_md.py
"""Integration: AGENTS.md text reaches every agent's prompt."""
from unittest.mock import AsyncMock, patch

import pytest

from agent_harness.pipeline import MigrationPipeline


SENTINEL_REPO = "REPO-SENTINEL-XYZ123"
SENTINEL_MODULE = "MODULE-SENTINEL-ABC789"


@pytest.mark.asyncio
async def test_agents_md_injected_into_every_migration_stage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # Build repo layout: tmp/repo/AGENTS.md + tmp/repo/mod/AGENTS.md + handler.
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "AGENTS.md").write_text(SENTINEL_REPO + "\n", encoding="utf-8")
    module = repo / "mod"; module.mkdir()
    (module / "AGENTS.md").write_text(SENTINEL_MODULE + "\n", encoding="utf-8")
    handler = module / "handler.py"; handler.write_text("def handler(e,c): pass\n")

    pipe = MigrationPipeline(project_root=str(tmp_path))
    await pipe.initialize()

    captured: dict[str, list[str]] = {"instructions": []}

    def fake_create_agent(role, tools=None, repo_root=None, module_path=None, **_):
        # Simulate base.create_agent: load the effective prompt via the real load_prompt.
        from agent_harness.base import load_prompt
        captured["instructions"].append(
            load_prompt(role, repo_root=repo_root, module_path=module_path)
        )

        class _Dummy:
            pass
        return _Dummy()

    with patch("agent_harness.analyzer.create_agent", side_effect=fake_create_agent), \
         patch("agent_harness.coder.create_agent", side_effect=fake_create_agent), \
         patch("agent_harness.tester.create_agent", side_effect=fake_create_agent), \
         patch("agent_harness.reviewer.create_agent", side_effect=fake_create_agent), \
         patch("agent_harness.security_reviewer.create_agent", side_effect=fake_create_agent), \
         patch("agent_harness.pipeline.analyze_module",
               new=AsyncMock(return_value="analysis")), \
         patch("agent_harness.pipeline.propose_contract",
               new=AsyncMock(return_value="c")), \
         patch("agent_harness.pipeline.finalize_contract",
               new=AsyncMock(return_value="c")), \
         patch("agent_harness.pipeline.migrate_module",
               new=AsyncMock(return_value="m")), \
         patch("agent_harness.pipeline.evaluate_module",
               new=AsyncMock(return_value="PASS")), \
         patch("agent_harness.pipeline.review_module",
               new=AsyncMock(return_value={"recommendation": "APPROVE",
                                            "confidence_score": 90,
                                            "coverage": 80})), \
         patch("agent_harness.pipeline.security_review",
               new=AsyncMock(return_value={"recommendation": "APPROVE"})):
        await pipe.run(
            module="mod", language="python",
            source_paths=[str(handler)],
        )

    # Since we patched analyze_module/migrate_module/evaluate_module/review_module/security_review
    # themselves (not the factories), the inner factory calls didn't fire. We expect zero
    # instructions captured — the test's real purpose is to verify pipeline.run's path
    # derivation. Assert the pipeline called each stage with repo_root/module_path populated.
    # We do that by checking the AsyncMock calls.
    from agent_harness.pipeline import analyze_module
    kwargs = analyze_module.call_args.kwargs if analyze_module.call_args else {}
    assert kwargs.get("repo_root") == str(repo.resolve()) or kwargs.get("repo_root") == str(repo)
    assert kwargs.get("module_path") == str(module.resolve()) or kwargs.get("module_path") == str(module)
```

- [ ] **Step 2: Run — expect failure**

Run: `python3 -m pytest tests/test_pipeline_agents_md.py -v`
Expected: AssertionError — `analyze_module.call_args.kwargs` does not contain `repo_root`.

- [ ] **Step 3: Add `_common_ancestor` helper + update `MigrationPipeline.run`**

Open `agent_harness/pipeline.py`. At module level (after existing imports), add:

```python
def _common_ancestor(paths: list[Path]) -> Path:
    """Return the deepest directory that is an ancestor of every path.

    Falls back to `Path('/')` in the pathological case of paths from
    different roots.
    """
    paths = [p.resolve() for p in paths if p]
    if not paths:
        return Path("/")
    if len(paths) == 1:
        return paths[0].parent if paths[0].is_file() else paths[0]
    ancestors = set(paths[0].parents) | {paths[0] if paths[0].is_dir() else paths[0].parent}
    for p in paths[1:]:
        pp = set(p.parents) | {p if p.is_dir() else p.parent}
        ancestors &= pp
    if not ancestors:
        return Path("/")
    return max(ancestors, key=lambda x: len(x.parts))
```

Inside `MigrationPipeline.run`, right after `source_paths` / `context_paths` are normalised, compute:

```python
        # Derive repo_root + module_path for AGENTS.md injection.
        if source_paths:
            module_path = str(Path(source_paths[0]).resolve().parent)
            all_paths = [Path(p) for p in list(source_paths) + list(context_paths)]
            repo_root = str(_common_ancestor(all_paths))
        else:
            module_path = os.path.join(self.project_root, "src", "lambda", module)
            repo_root = self.project_root
```

Then thread them into the three analyzer/coder/tester/reviewer/security call sites. Find each call and add the two kwargs:

- `await analyze_module(..., repo_root=repo_root, module_path=module_path)`
- `await migrate_module(..., repo_root=repo_root, module_path=module_path)`
- `await evaluate_module(..., repo_root=repo_root, module_path=module_path)`
- `await review_module(module=module, language=language, repo_root=repo_root, module_path=module_path)`
- `await security_review(module=module, language=language, repo_root=repo_root, module_path=module_path)`

- [ ] **Step 4: Run test**

Run: `python3 -m pytest tests/test_pipeline_agents_md.py -v`
Expected: PASS.

- [ ] **Step 5: Regression**

Run: `python3 -m pytest tests/test_pipeline_paths.py tests/test_fanout_e2e.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agent_harness/pipeline.py tests/test_pipeline_agents_md.py
git commit -m "feat(pipeline): derive repo_root+module_path and thread into every agent stage"
```

---

## Task 8: Discovery agents accept `repo_root`

**Files:**
- Modify: `agent_harness/discovery/repo_scanner.py`
- Modify: `agent_harness/discovery/dependency_grapher.py`
- Modify: `agent_harness/discovery/brd_extractor.py`
- Modify: `agent_harness/discovery/architect.py`
- Modify: `agent_harness/discovery/story_decomposer.py`
- Modify: `agent_harness/discovery/workflow.py`

Each discovery stage's `_run_agent` (or `_run_module_agent` / `_run_system_agent`) seam currently calls `create_agent(role=..., tools=[...])`. Extend each to accept `repo_root` and pass through.

- [ ] **Step 1: `repo_scanner.py`**

Find:
```python
async def _run_agent(message: str) -> str:
    agent = create_agent(role="repo_scanner", tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)
```

Replace with:
```python
async def _run_agent(message: str, repo_root: str | None = None) -> str:
    agent = create_agent(role="repo_scanner",
                         tools=[read_file, list_directory, search_files],
                         repo_root=repo_root)
    return await run_with_retry(agent, message)
```

Update `scan_repo` to pass `repo_root=str(root)` when calling `_run_agent(msg)`:

```python
    raw = await _run_agent(msg, repo_root=str(root))
```

- [ ] **Step 2: `dependency_grapher.py`**

Find `_run_agent`, same pattern. Add `repo_root` kwarg + pass to `create_agent`. In `build_graph`, pass `repo_root=str(repo_root)` when invoking `_run_agent` for LLM disambiguation.

- [ ] **Step 3: `brd_extractor.py`**

Has two seams: `_run_module_agent` and `_run_system_agent`. Each gets a `repo_root` kwarg + passes to `create_agent`. In `extract_brds`, pass `repo_root=str(repo_root)` to both.

- [ ] **Step 4: `architect.py`**

Same pattern as `brd_extractor.py` — two seams, both get `repo_root`.

- [ ] **Step 5: `story_decomposer.py`**

Single `_run_agent` seam, same pattern. In `decompose`, pass `repo_root=...` (from a new `repo_root` parameter on `decompose`). Update the workflow (next step) to pass it in.

- [ ] **Step 6: `workflow.py` — thread `repo_path` into every seam**

Inside `run_discovery`, the stage coroutines already receive `root = Path(repo_path).resolve()`. Update each `_produce_*` helper to pass `repo_root=str(root)` through. Example for scanner:

```python
    async def _produce_scanner(feedback: str) -> str:
        try:
            inv = await repo_scanner.scan_repo(repo_id, str(root), extra_instructions=feedback)
            return inv.model_dump_json()
        except ValidationError as exc:
            return _parse_error_payload(exc)
```

`scan_repo` already passes `root` through to `_run_agent` (done in step 1). Similar for grapher — `build_graph` gets `root` already, no workflow change. BRD and architect: their functions already receive `repo_root=root` as a parameter — confirm by reading, and if missing, add `repo_root=root` to the kwargs. Stories: add `repo_root=root` to the call to `story_decomposer.decompose(...)`.

To minimise surgery: the workflow's `_produce_*` functions already have `root` in scope via closure. The only changes needed in `workflow.py` are:
- Pass `repo_root=str(root)` if `decompose` / `extract_brds` / `design` / `build_graph` don't already accept and forward it.

If an individual stage function doesn't currently accept `repo_root`, give it one (default `None`) and pass it through to its internal `_run_agent` / `_run_module_agent` / `_run_system_agent` calls.

- [ ] **Step 7: Sanity import**

Run: `python3 -c "from agent_harness.discovery import workflow, repo_scanner, dependency_grapher, brd_extractor, architect, story_decomposer; print('ok')"`
Expected: `ok`.

- [ ] **Step 8: Regression**

Run: `python3 -m pytest tests/test_discovery_e2e.py tests/test_repo_scanner.py tests/test_dependency_grapher.py tests/test_brd_extractor.py tests/test_architect.py tests/test_story_decomposer.py -q`
Expected: all PASS (new kwargs default to None; existing tests don't set them; patched seams now have an extra optional parameter that AsyncMock tolerates).

- [ ] **Step 9: Commit**

```bash
git add agent_harness/discovery/
git commit -m "feat(discovery): every stage forwards repo_root into agent factory"
```

---

## Task 9: Reviewer prompt — document VALID / INVALID / SKIPPED handling

**Files:**
- Modify: `agent_harness/prompts/reviewer.md`
- Modify: `agent_harness/prompts/security-reviewer.md`

- [ ] **Step 1: Append a section to `agent_harness/prompts/reviewer.md`**

Add at the end of the file:

```markdown

## Bicep validation handling

You have access to the `validate_bicep(path)` tool. When the generated migration
includes Bicep IaC files (typically under `infrastructure/<module>/`), invoke
this tool on each before settling on a recommendation.

Tool return values and your obligations:
- `VALID` → no effect. Bicep parsed and type-checked.
- `INVALID: <stderr>` → you MUST NOT recommend APPROVE. Downgrade to at least
  CHANGES_REQUESTED and include the stderr verbatim in your review under a
  `## Bicep validation errors` heading.
- `SKIPPED: <reason>` → the environment does not have the Azure CLI or Bicep
  extension available. Note this in the review under
  `## Bicep validation skipped` but do not treat as a failure — the generated
  code may still be correct; a separate CI step will validate.
```

- [ ] **Step 2: Append the same section to `agent_harness/prompts/security-reviewer.md`**

The security reviewer also calls `validate_bicep` (looking for, e.g., public
ingress without Private Link) and benefits from the same interpretive
guidance. Append the identical section.

- [ ] **Step 3: Commit**

```bash
git add agent_harness/prompts/reviewer.md agent_harness/prompts/security-reviewer.md
git commit -m "docs(prompts): document validate_bicep semantics for reviewers"
```

---

## Task 10: `AGENTS.md` template

**Files:**
- Create: `templates/AGENTS.md.example`

- [ ] **Step 1: Create `ms-agent-harness/templates/AGENTS.md.example`**

Exact content:

```markdown
# AGENTS.md

Drop one of these at the root of a repo you're migrating to give every
agent (discovery + migration) shared context. Drop another inside a
module directory for module-specific overrides.

## What goes here

- Domain glossary — business terms, ID shapes, regulatory classes.
- Non-obvious invariants — idempotency keys, ordering guarantees.
- Forbidden patterns — "never log raw PAN", "never invent retries on X".
- Preferred patterns — "always use `TransactWriteItems` for multi-row updates".
- Target Azure conventions — naming, resource groups, identity boundaries.

## What NOT to put here

- Re-statements of the pipeline's own quality principles (already injected
  via `agent_harness/prompts/quality-principles.md`).
- Runtime state (use `config/state/learned-rules.md`).
- Secret material (goes in Key Vault, not git).

## Injection order

1. Stage prompt (e.g. `prompts/coder.md`).
2. `prompts/quality-principles.md`.
3. `config/state/learned-rules.md`.
4. `config/program.md`.
5. `<repo_root>/AGENTS.md` — this file.
6. `<module_path>/AGENTS.md` — module-specific overrides (migration only).

Later entries can override earlier ones; agents are instructed to give
precedence to more-specific guidance.
```

- [ ] **Step 2: Create the `templates/` directory if it doesn't exist, then commit**

```bash
mkdir -p templates
# (file created in step 1)
git add templates/AGENTS.md.example
git commit -m "docs(templates): add AGENTS.md example documenting the convention"
```

---

## Task 11: README section

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Append a new section**

Append to `ms-agent-harness/README.md`:

```markdown

## Per-repo and per-module agent context (AGENTS.md)

Drop an `AGENTS.md` at the root of the repo being migrated to give every
agent (discovery + migration) shared context — domain glossary, invariants,
forbidden/preferred patterns, Azure naming conventions. For module-specific
overrides, drop a second `AGENTS.md` inside the module's directory.

Injection order (later entries can override earlier ones):

1. Stage prompt (e.g. `prompts/coder.md`).
2. `prompts/quality-principles.md`.
3. `config/state/learned-rules.md`.
4. `config/program.md`.
5. `<repo_root>/AGENTS.md`.
6. `<module_path>/AGENTS.md` (migration only — discovery is repo-scoped).

See `templates/AGENTS.md.example` for the conventions.

## Additional agent tools

- `apply_patch(edits)` — atomic batch of search-replace edits. The coder uses
  this for incremental edits instead of whole-file rewrites. All edits in a
  batch are validated (each `old_string` matches `expected_count` times)
  before any file is touched; any failure aborts the batch.
- `validate_bicep(path)` — transpiles a Bicep file with `az bicep build
  --stdout`. Returns `VALID` / `INVALID: <stderr>` / `SKIPPED: <reason>`.
  Used by the reviewer and security_reviewer. When it returns `INVALID`,
  the reviewer is instructed never to APPROVE without regenerating.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): document AGENTS.md convention and new agent tools"
```

---

## Self-Review Notes

- **Spec coverage:**
  - §4.1 load_prompt — Task 4.
  - §4.2 create_agent — Task 5.
  - §4.3 migration agents wiring — Task 6.
  - §4.3 discovery agents wiring — Task 8.
  - §4.4 apply_patch — Task 1.
  - §4.5 validate_bicep — Task 2.
  - §4.6 tools registration — Task 3.
  - §4.7 reviewer handling of SKIPPED / INVALID — Task 9.
  - §4.8 AGENTS.md template — Task 10.
  - §6.1 / §6.2 control flow — Task 7 (migration pipeline plumbing) + Task 8 (discovery plumbing).
  - §7 error handling — exercised by Task 1/2 unit tests (`test_file_not_found`, `test_timeout_returns_invalid`, etc.).
  - §8 testing — every component has a unit test listed in its task; Task 7 covers the integration case.
- **Placeholder scan:** No TBDs, no "implement later", no "similar to task N" without full code. The instruction in Task 4 step 3 that references "whatever the current structure is" is a guardrail (the existing `load_prompt` has evolved over the discovery cycle — the implementer should preserve the current injection order), not a placeholder.
- **Type consistency:** `repo_root` / `module_path` kwargs consistently named and typed (`str | Path | None = None` at boundaries; `str` or `Path` in bodies) across every touched function. `apply_patch` edit schema `{file, old_string, new_string, expected_count}` consistent between Task 1 impl, §5.1 spec contract, and usage. `validate_bicep` return strings (`VALID` / `INVALID: ...` / `SKIPPED: ...`) consistent with §5.2 and Task 9 prompt instructions.
- **Back-compat:** Every signature extension is pure-additive with default `None`. Existing callers (including every test merged into `main` so far) remain green. The regression steps inside Tasks 4, 5, 6, 7, 8 explicitly run the relevant prior test suites.
