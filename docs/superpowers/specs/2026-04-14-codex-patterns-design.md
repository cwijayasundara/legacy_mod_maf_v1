# Codex-OSS Pattern Extraction (Sub-project D.1) — Design Spec

**Date:** 2026-04-14
**Status:** Draft — pending review
**Target repo:** `ms-agent-harness`
**Depends on:** all prior sub-projects (A/B/C) merged.

---

## 1. Context

The existing `ms-agent-harness` injects three static context files into every
agent prompt via `agent_harness/base.py::load_prompt`:

- `agent_harness/prompts/quality-principles.md`
- `config/state/learned-rules.md`
- `config/program.md`

These are harness-owned. There is no mechanism for **repo-specific** or
**module-specific** context that travels with the code being migrated. Users
cannot override prompts per project, nor give a module-level hint ("this
handler is idempotent on `request_id`; don't invent other uniqueness rules")
without editing the harness itself.

Separately, agents today write to files via a single tool — `write_file(path,
content)` — which rewrites the whole file on every edit. Whole-file rewrites
are expensive (tokens), risky (LLMs can silently drop unrelated code), and
produce noisy diffs. Codex-OSS and Claude Code-style harnesses converge on
**search-replace editing** as the primary edit primitive; the harness
validates a unique-match precondition before touching disk.

Finally, the harness generates Bicep templates but never validates them.
LLM-generated Bicep routinely has wrong property names, missing required
params, or undefined symbol references. Catching these before the human
reviewer sees them cuts review cycles meaningfully.

This spec extracts three Codex-OSS patterns to close those gaps:

1. **`AGENTS.md` context injection.**
2. **`apply_patch` search-replace edit tool.**
3. **`validate_bicep` IaC validation tool.**

This is sub-project D.1. Sub-project D.2 (harness hardening — timeouts,
cancellation, structured logging) is a separate cycle.

## 2. Scope

### In scope

- Extend `base.load_prompt` to accept optional `repo_root` and `module_path`,
  injecting `<repo_root>/AGENTS.md` and `<module_path>/AGENTS.md` when
  present. Existing injection order (`quality-principles`, `learned-rules`,
  `program.md`) preserved; AGENTS.md appended after.
- Thread `repo_root` and `module_path` through `create_agent` for both
  migration agents (analyzer/coder/tester/reviewer/security_reviewer) and
  discovery agents.
- New `agent_harness/tools/patch_tool.py` exposing `apply_patch(edits)`.
- New `agent_harness/tools/bicep_tool.py` exposing `validate_bicep(path)`.
- Register `apply_patch` in the coder's tool list and `validate_bicep` in
  the reviewer + security_reviewer tool lists.
- Create `ms-agent-harness/templates/AGENTS.md.example` documenting the
  convention.
- Unit tests for each new unit; one mocked-LLM integration test that
  asserts AGENTS.md text reaches the agent prompt.

### Out of scope (future cycles)

- Explicit plan files (coder writes `migration-plan.md` before coding). Valid
  but lower-impact; defer.
- `shell` tool. Powerful but requires careful sandboxing; not v1.
- `structured_diff` tool. Nice-to-have; defer.
- AGENTS.md per-stage files (`AGENTS.analyzer.md`). Fragments guidance; defer.
- Auto-scaffolding (harness generates a starter `AGENTS.md`). Manual
  authoring works; auto-generation invites stale templates.
- Giving `apply_patch` to tester / reviewer / security_reviewer. Only the
  coder writes code in v1.
- Live-Azure validation via `az deployment group validate`. Belongs in
  post-migration CI, not inside an agent-callable tool.
- Discovery agents reading `<module_path>/AGENTS.md`. Discovery is
  repo-scoped; module-level files only apply to migration.

## 3. Architecture

### 3.1 Placement

```
ms-agent-harness/
├── agent_harness/
│   ├── base.py                           [modify] load_prompt, create_agent
│   ├── pipeline.py                       [modify] thread paths into agents
│   ├── analyzer.py / coder.py / tester.py / reviewer.py / security_reviewer.py
│   │                                     [modify] each call to create_agent
│   ├── discovery/
│   │   ├── repo_scanner.py / dependency_grapher.py / brd_extractor.py /
│   │   │ architect.py / story_decomposer.py
│   │   │                                 [modify] pass repo_root into create_agent
│   │   └── workflow.py                   [modify] thread repo_path into stage agent factories
│   └── tools/
│       ├── __init__.py                   [modify] re-export new tools
│       ├── patch_tool.py                 [NEW] apply_patch
│       └── bicep_tool.py                 [NEW] validate_bicep
└── templates/
    └── AGENTS.md.example                 [NEW]

tests/
├── test_load_prompt_agents_md.py         [NEW]
├── test_patch_tool.py                    [NEW]
├── test_bicep_tool.py                    [NEW]
└── test_pipeline_agents_md.py            [NEW] integration
```

### 3.2 Reuse of existing infrastructure

- `load_prompt` already injects the three static files; AGENTS.md injection
  is additive to that logic.
- `@tool(approval_mode="never_require")` from `agent_framework` — same
  decorator existing tools use.
- `MigrationPipeline.run` already derives `source_dir` from `source_paths`
  (sub-project B). We add `module_path` = that `source_dir`, and
  `repo_root` = the nearest common ancestor of `source_paths + context_paths`.
- `conftest.py` mock for `agent_framework.tool` — existing tests continue to
  work without change.

## 4. Components

### 4.1 `base.load_prompt` — AGENTS.md injection

Signature change:

```python
def load_prompt(role: str,
                repo_root: str | Path | None = None,
                module_path: str | Path | None = None) -> str:
```

New behaviour, appended *after* the existing `quality-principles`,
`learned-rules`, and `program.md` injection:

```python
    if repo_root:
        agents_md = Path(repo_root) / "AGENTS.md"
        if agents_md.is_file():
            try:
                prompt += (
                    f"\n\n## Repo context (AGENTS.md)\n"
                    f"{agents_md.read_text(encoding='utf-8')}"
                )
            except OSError as exc:
                logger.warning("Could not read %s: %s", agents_md, exc)

    if module_path:
        mod_md = Path(module_path) / "AGENTS.md"
        if mod_md.is_file():
            try:
                prompt += (
                    f"\n\n## Module context (AGENTS.md)\n"
                    f"{mod_md.read_text(encoding='utf-8')}"
                )
            except OSError as exc:
                logger.warning("Could not read %s: %s", mod_md, exc)
```

No merge logic. Both files go in with clear headers; order (module after
repo) signals precedence to the agent. An AGENTS.md of 0 bytes is injected
as an empty section — harmless.

### 4.2 `base.create_agent` — accept `repo_root` / `module_path`

```python
def create_agent(role: str, tools: list | None = None,
                 repo_root: str | Path | None = None,
                 module_path: str | Path | None = None) -> Agent:
    ...
    prompt = load_prompt(role, repo_root=repo_root, module_path=module_path)
    ...
```

Back-compat: the two new kwargs default to `None`; every existing call site
works unchanged. Each call site that *should* pass paths gets updated in
the individual agent modules (§4.3).

### 4.3 Per-agent wiring

**Migration stages:**

`agent_harness/analyzer.py::create_analyzer(repo_root=None, module_path=None)`
— forwards the kwargs into `create_agent`. Similar one-line change in
`coder.py::create_coder`, `tester.py::create_tester`,
`reviewer.py::create_reviewer`, `security_reviewer.py::create_security_reviewer`.

`MigrationPipeline.run` derives:

```python
if source_paths:
    module_path = str(Path(source_paths[0]).parent)
    all_paths = list(source_paths) + list(context_paths)
    repo_root = str(_common_ancestor([Path(p) for p in all_paths]))
else:
    module_path = os.path.join(project_root, "src", "lambda", module)
    repo_root = project_root
```

and threads them into every factory call. `_common_ancestor` is a small
helper (~10 lines) in `agent_harness/pipeline.py`.

**Discovery stages:**

Each discovery stage's `_run_agent` seam already constructs the agent per
call. Extend each to accept a `repo_root` kwarg defaulting to `None`, and
pass it into `create_agent`. Then `run_discovery(repo_id, repo_path, repo)`
threads `repo_root=repo_path` into every stage call.

No `module_path` for discovery — discovery is repo-scoped, not per-module.

### 4.4 `apply_patch` tool

`agent_harness/tools/patch_tool.py`:

```python
"""Search-replace editing tool. All-or-nothing batch semantics."""
from __future__ import annotations

from pathlib import Path

from agent_framework import tool


@tool(approval_mode="never_require")
def apply_patch(edits: list[dict]) -> str:
    """Apply a batch of search-replace edits atomically.

    Each edit is a dict: {file, old_string, new_string, expected_count}.
    `expected_count` defaults to 1. All edits are validated before any
    file is touched; any failure aborts the entire batch.

    Returns a summary string. On failure, returns 'ERROR: <reason>' and
    leaves every file untouched.
    """
    # Validate pass.
    plans: list[tuple[Path, str, str, int]] = []
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
        plans.append((path, content, new, expected))

    # Apply pass.
    written: list[str] = []
    for (path, content, new, expected), edit in zip(plans, edits):
        old = edit["old_string"]
        updated = content.replace(old, new, expected)
        path.write_text(updated, encoding="utf-8")
        written.append(str(path))

    return f"applied {len(edits)} edit(s) to {len(set(written))} file(s)"
```

Design notes:
- All-or-nothing: validate every edit first, then apply. Never a
  half-applied batch. No manual rollback needed — if validation passes,
  application won't fail (unless the FS changes mid-function, which is
  vanishingly rare and acceptable).
- `expected_count` supports rare mass-replace use cases (rename a helper
  across a file: `expected_count=5`).
- `write_text` is a full rewrite at the OS level, but the content is the
  precomputed `updated` string — no partial writes on LLM error.

### 4.5 `validate_bicep` tool

`agent_harness/tools/bicep_tool.py`:

```python
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
    # Bicep emits warnings to stderr with returncode 0 when harmless; we
    # only reach here on non-zero exit.
    stderr = (result.stderr or "").strip()[:2000]
    if "No module named 'bicep'" in stderr or "is not installed" in stderr.lower():
        return f"SKIPPED: bicep extension not available: {stderr}"
    return f"INVALID: {stderr}"
```

Notes:
- 30s timeout is generous; `az bicep build` on a typical template takes
  <3s. Longer typically means `az` is bootstrapping.
- SKIPPED is not a failure from the reviewer's perspective — the reviewer
  should treat SKIPPED as "no signal" rather than "broken". §5 covers this
  in the reviewer's handling.

### 4.6 Tool registration

`agent_harness/tools/__init__.py` re-exports:

```python
from .patch_tool import apply_patch
from .bicep_tool import validate_bicep
```

Coder gets `apply_patch` added to its `tools=[...]`. Reviewer + security_reviewer
get `validate_bicep` added.

### 4.7 Reviewer handling of SKIPPED / INVALID

The reviewer's existing quality gates produce a recommendation (APPROVE /
CHANGES_REQUESTED / BLOCKED) and a confidence score. Bicep validation is
additive:

- `VALID` → no effect (already expected).
- `INVALID: <stderr>` → the reviewer must not APPROVE; downgrade to at
  least CHANGES_REQUESTED and include the stderr in its report.
- `SKIPPED: <reason>` → no effect on recommendation; note in the report
  that validation was unavailable.

The reviewer's prompt file (`agent_harness/prompts/reviewer.md`) gets a new
section documenting this. No code change beyond what's already described.

### 4.8 AGENTS.md template

`ms-agent-harness/templates/AGENTS.md.example`:

```markdown
# AGENTS.md

Drop one of these at the root of a repo you're migrating to give every
agent (discovery + migration) shared context. Drop another inside a
module directory for module-specific overrides.

## What goes here

- Domain glossary — business terms, ID shapes, regulatory classes.
- Non-obvious invariants — idempotency keys, ordering guarantees.
- Forbidden patterns — "never log raw PAN", "never invent retries on X".
- Preferred patterns — "always use `TransactWriteItems` for multi-row
  updates".
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

## 5. Data contracts

### 5.1 `apply_patch` edit

```json
{
  "file": "<absolute or workspace-relative path>",
  "old_string": "<exact substring to replace>",
  "new_string": "<replacement>",
  "expected_count": 1
}
```

Returned summary (success): `"applied N edit(s) to M file(s)"`.
Returned summary (failure): `"ERROR: <human-readable reason>"`.

### 5.2 `validate_bicep` return

Literal strings:

- `"VALID"`
- `"INVALID: <stderr-truncated-to-2000-chars>"`
- `"SKIPPED: az CLI not installed"`
- `"SKIPPED: bicep extension not available: <stderr>"`

## 6. Control flow

### 6.1 `/migrate` happy path

```
POST /migrate {module, source_paths, context_paths, …}
 → MigrationPipeline.run(…)
    ├─ derive module_path = source_paths[0].parent
    ├─ derive repo_root    = common_ancestor(source_paths + context_paths)
    ├─ analyzer  = create_analyzer(repo_root, module_path)   # sees AGENTS.md
    ├─ coder     = create_coder(repo_root, module_path)      # sees AGENTS.md + apply_patch
    ├─ tester    = create_tester(repo_root, module_path)     # sees AGENTS.md
    ├─ reviewer  = create_reviewer(repo_root, module_path)   # sees AGENTS.md + validate_bicep
    └─ security  = create_security_reviewer(repo_root, module_path)  # AGENTS.md + validate_bicep
```

Legacy call (no `source_paths`): derives `module_path =
PROJECT_ROOT/src/lambda/<module>`, `repo_root = PROJECT_ROOT`. Existing
layouts pick up a repo-level AGENTS.md for free.

### 6.2 `/discover` happy path

```
POST /discover {repo_id, repo_path}
 → run_discovery(repo_id, repo_path, repo)
    ├─ scanner   = create_agent(role="repo_scanner",   repo_root=repo_path)
    ├─ grapher   = create_agent(role="dependency_grapher", repo_root=repo_path)
    ├─ brd       = create_agent(role="brd_extractor",  repo_root=repo_path)
    ├─ architect = create_agent(role="architect",      repo_root=repo_path)
    └─ stories   = create_agent(role="story_decomposer", repo_root=repo_path)
```

`module_path` stays `None` for every discovery call.

## 7. Error handling

| Condition | Behaviour |
|---|---|
| AGENTS.md missing | Silently skip that section (it's optional). |
| AGENTS.md exists but unreadable | Log warning, skip. Don't crash. |
| AGENTS.md is huge (>1MB) | Still injected (no truncation in v1). Budget is the LLM's problem; hardening (timeouts + token limits) lands in D.2. |
| `apply_patch` edit file missing | Full batch aborts; `"ERROR: edit i: file not found"`. |
| `apply_patch` `old_string` not found | Same — batch aborts. |
| `apply_patch` `old_string` matches wrong count | Same. |
| `apply_patch` write fails (disk full, permissions) | Raised to caller as `OSError`; partial write is possible only for edits already applied before this one. Caller (the agent) sees the exception in its tool result. v1 accepts this rare case; D.2 can add a temp-file+rename atomic dance. |
| `validate_bicep` — az not installed | Return `SKIPPED`. Reviewer does not treat SKIPPED as failure. |
| `validate_bicep` — bicep ext missing | Same. |
| `validate_bicep` — timeout | Return `INVALID: timeout after 30s`. Treated as failure. |
| `validate_bicep` — non-zero exit | Return `INVALID: <stderr>`. Treated as failure. |

## 8. Testing

Unit (no LLM):

- `tests/test_load_prompt_agents_md.py`
  - `test_neither_file_present` — call `load_prompt("coder", repo_root=X, module_path=Y)` where neither exists; prompt does not contain `## Repo context` or `## Module context` headers.
  - `test_repo_only` — only `<repo_root>/AGENTS.md` exists; prompt has the repo header and text, not the module header.
  - `test_module_only` — only `<module_path>/AGENTS.md` exists.
  - `test_both_present_order_correct` — both exist; repo section appears before module section in the prompt.
  - `test_back_compat_no_kwargs` — `load_prompt("coder")` with no kwargs behaves exactly as before (no AGENTS.md sections).
- `tests/test_patch_tool.py`
  - `test_single_edit_happy_path` — one edit applied, file contents changed.
  - `test_batch_multi_file` — three edits across two files; all applied.
  - `test_edit_rejected_when_old_string_missing` — batch aborts; neither file touched.
  - `test_edit_rejected_when_old_string_duplicated` — `expected_count=1` but string appears twice → abort.
  - `test_expected_count_greater_than_one` — intentional mass replace, passes when count matches.
  - `test_file_not_found` — batch aborts with clear message.
- `tests/test_bicep_tool.py`
  - `test_valid_bicep_transpiles` — fixture with a trivial valid Bicep file; monkeypatch `subprocess.run` to return `returncode=0`. Assert `"VALID"`.
  - `test_invalid_bicep_returns_stderr` — monkeypatch to return `returncode=1, stderr="Error BCP..."`. Assert `"INVALID: Error BCP..."`.
  - `test_az_missing_returns_skipped` — monkeypatch `subprocess.run` to raise `FileNotFoundError`. Assert starts with `"SKIPPED"`.
  - `test_timeout_returns_invalid` — monkeypatch to raise `subprocess.TimeoutExpired`. Assert `"INVALID: timeout after 30s"`.
  - `test_file_not_found_on_disk` — path doesn't exist; returns `"INVALID: file not found"`.

Integration (mocked LLM):

- `tests/test_pipeline_agents_md.py`
  - Create a tmp repo layout: `tmp/repo/AGENTS.md` with a distinctive
    sentinel string, and a `tmp/repo/handler.py`. Call
    `MigrationPipeline.run(module="x", language="python",
    source_paths=[tmp/repo/handler.py])` with `analyze_module` /
    `migrate_module` / `evaluate_module` / `review_module` /
    `security_review` all patched as `AsyncMock`. Capture the prompt each
    agent factory produced (by monkeypatching `create_agent` to record
    the `instructions` string each call). Assert the sentinel text
    appears in every captured prompt.

Real-LLM: none in unit suite. Manual check via running `/migrate` after
dropping an AGENTS.md into the target repo.

## 9. Migration plan (how this ships)

1. `apply_patch` tool + unit tests.
2. `validate_bicep` tool + unit tests.
3. `base.load_prompt` AGENTS.md injection + unit tests.
4. `base.create_agent` signature extension (back-compat).
5. Per-agent wiring — each migration agent module's `create_*` function
   gains the two kwargs and forwards them.
6. `MigrationPipeline.run` derives `repo_root` + `module_path` and threads
   them into every `create_*` call. Includes the `_common_ancestor` helper.
7. Discovery stage wiring — each discovery stage's `_run_agent` accepts
   and forwards `repo_root`. `run_discovery` threads `repo_path`.
8. Tool registration — `tools/__init__.py` re-exports; coder's agent
   factory adds `apply_patch`; reviewer + security_reviewer add
   `validate_bicep`.
9. Reviewer prompt update — documents how to interpret SKIPPED / INVALID.
10. Integration test.
11. `templates/AGENTS.md.example` + README section.

Each step is independently testable; order minimises blocking.

## 10. Open questions (none blocking)

- Should `apply_patch` support "create file if missing" via an empty
  `old_string`? Useful; defer to D.2 (behaviour change; more test cases
  needed).
- Should the reviewer's prompt explicitly say "never APPROVE when
  `validate_bicep` returned INVALID"? Leaning yes, covered in §4.7. Will
  be part of the reviewer prompt edit in the implementation plan.
- For hugely nested repos, `_common_ancestor` could walk to the
  filesystem root if `source_paths` and `context_paths` live on different
  drives. In practice both are always under the repo; v1 accepts the
  naive implementation and D.2 can add a `min(depth, repo_root_hint)`
  guard if needed.

---

**Next step:** user reviews, then implementation plan via `writing-plans`.
