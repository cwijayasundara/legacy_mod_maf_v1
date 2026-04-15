"""DependencyGrapher — deterministic-first graph build with LLM fallback."""
from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

from ..base import create_agent, run_with_retry
from ..tools.file_tools import read_file, list_directory, search_files
from .artifacts import DependencyGraph, Inventory
from .tools.aws_sdk_patterns import resolve
from .tools.graph_io import GraphBuilder, save
from .tools.tree_sitter_py import Boto3Call, extract_boto3_calls, parse_imports
from . import paths

logger = logging.getLogger("discovery.grapher")


async def _run_agent(message: str, repo_root: str | None = None) -> str:
    """LLM invocation seam — patched in tests."""
    agent = create_agent(role="dependency_grapher",
                         tools=[read_file, list_directory, search_files],
                         repo_root=repo_root)
    return await run_with_retry(agent, message)


async def build_graph(repo_id: str, repo_root: Path,
                      inventory: Inventory,
                      extra_instructions: str = "") -> DependencyGraph:
    """Build the graph deterministically; invoke LLM only for ambiguous calls.

    For each module, walk imports transitively across the whole repo (not just
    the module's own path) so shared library files like ``services/aws_clients.py``
    contribute their boto3 calls and resource references back to the importing
    handler. This matches the user's mental model: ``SOURCE_DIR`` = whole repo,
    grapher = comprehensive graph.
    """
    repo_root = Path(repo_root).resolve()
    builder = GraphBuilder()
    module_paths: dict[str, Path] = {}
    handler_files: dict[str, Path] = {}

    for m in inventory.modules:
        builder.add_module(m.id, attrs={"path": m.path, "language": m.language})
        module_paths[m.id] = repo_root / m.path
        entry = repo_root / m.handler_entrypoint
        handler_files[m.id] = entry if entry.is_file() else module_paths[m.id]

    module_ids = set(module_paths)
    # Map repo-relative dotted path → absolute file for in-repo Python files.
    # Supports both dir/__init__.py and bare file.py imports.
    file_index = _index_python_files(repo_root)
    ambiguous_calls: list[tuple[str, str]] = []

    for m in inventory.modules:
        seeds = _collect_seed_files(m, repo_root)
        reachable = _reachable_files(seeds, repo_root, file_index)
        for py_file in sorted(reachable):
            rel = py_file.relative_to(repo_root)
            is_shared_lib = py_file not in seeds
            if is_shared_lib:
                lib_id = _library_node_id(rel)
                builder.add_library(lib_id, attrs={"file": str(rel)})
                builder.add_edge(m.id, lib_id, "imports")

            for imp in parse_imports(str(py_file)):
                target = _import_to_module(imp.module, m.id, module_ids)
                if target and target != m.id:
                    builder.add_edge(m.id, target, "imports")

            name_bindings = _collect_name_bindings(str(py_file))
            for call in extract_boto3_calls(str(py_file)):
                ref = resolve(call)
                if ref is None:
                    ambiguous_calls.append(
                        (m.id, f"{call.file}:{call.line} {call.service}.{call.method}")
                    )
                    continue
                resource_name = ref.name or _lookup_binding(
                    str(py_file), call, name_bindings,
                )
                if resource_name is None:
                    ambiguous_calls.append(
                        (m.id, f"{call.file}:{call.line} {call.service}.{call.method}")
                    )
                    continue
                node = builder.add_resource(ref.kind, resource_name)
                builder.add_edge(m.id, node, ref.access)

    if ambiguous_calls:
        listing = "\n".join(f"- module={mid}: {ctx}" for mid, ctx in ambiguous_calls)
        msg = (
            "Resolve these ambiguous boto3 call sites to (resource_kind, resource_name).\n"
            "Return JSON: [{\"module\": \"...\", \"resource_kind\": \"...\", \"resource_name\": \"...\", \"access\": \"reads|writes|produces|consumes|invokes\"}]\n\n"
            f"{listing}\n\n{extra_instructions}"
        )
        raw = await _run_agent(msg, repo_root=str(repo_root))
        try:
            for entry in json.loads(_strip_fences(raw)):
                node = builder.add_resource(entry["resource_kind"], entry["resource_name"])
                builder.add_edge(entry["module"], node, entry["access"])
        except Exception as exc:
            logger.warning("LLM disambiguation skipped: %s", exc)

    g = builder.build()
    save(g, paths.graph_path(repo_id))
    return g


_NAMED_FACTORY_METHODS = {"Table", "Queue", "Topic", "Bucket", "Object", "Stream"}


def _collect_name_bindings(path: str) -> dict[str, str]:
    """Map local variable -> AWS resource name via patterns like
    `x = boto3.resource("dynamodb").Table("Orders")` or `x = ddb.Table("Orders")`.
    """
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"),
                         filename=path)
    except SyntaxError:
        return {}
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
           and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        if target is None or not isinstance(value, ast.Call):
            continue
        name = _literal_name_from_call(value)
        if name is not None:
            bindings[target] = name
    return bindings


def _literal_name_from_call(call: ast.Call) -> str | None:
    """Return the string literal from a named-factory call like `.Table("Orders")`."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in _NAMED_FACTORY_METHODS:
        if call.args and isinstance(call.args[0], ast.Constant) \
           and isinstance(call.args[0].value, str):
            return call.args[0].value
    return None


def _lookup_binding(path: str, call: Boto3Call,
                    bindings: dict[str, str]) -> str | None:
    """Find `receiver.method(...)` at call.line and return the receiver's bound name."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"),
                         filename=path)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or node.lineno != call.line:
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == call.method \
           and isinstance(node.func.value, ast.Name):
            return bindings.get(node.func.value.id)
    return None


def _import_to_module(module: str, current: str, module_ids: set[str]) -> str | None:
    """Map a Python import to a known module id, if any."""
    if module.startswith("."):
        return None
    head = module.split(".", 1)[0]
    return head if head in module_ids else None


_EXCLUDE_PARTS = {".git", "__pycache__", "node_modules", ".venv", "venv", "tests"}


def _index_python_files(repo_root: Path) -> dict[str, Path]:
    """Map dotted module paths (repo-relative) to the file that defines them.

    Supports both ``pkg/mod.py`` → ``pkg.mod`` and ``pkg/__init__.py`` → ``pkg``.
    """
    index: dict[str, Path] = {}
    for py in repo_root.rglob("*.py"):
        if any(part in _EXCLUDE_PARTS for part in py.relative_to(repo_root).parts):
            continue
        rel = py.relative_to(repo_root)
        parts = list(rel.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        index[".".join(parts)] = py
    return index


def _collect_seed_files(module, repo_root: Path) -> set[Path]:
    """Seed files for a module's reachability walk.

    For folder-per-handler layouts (handler_entrypoint inside its own module dir):
    include every .py file under that directory.

    For flat layouts (many handlers sharing one dir): include ONLY the
    handler's entrypoint file, so each handler's transitive set is attributed
    to that handler alone.
    """
    entry = (repo_root / module.handler_entrypoint).resolve()
    mod_dir = (repo_root / module.path).resolve()
    seeds: set[Path] = set()
    if entry.is_file():
        seeds.add(entry)
    # Heuristic: folder-per-handler if the module path is a dedicated subtree whose
    # only .py entry points are under this module (checked loosely: the dir's name
    # equals the module id). Otherwise treat as flat and seed only the entrypoint.
    if mod_dir.is_dir() and mod_dir.name == module.id:
        for p in mod_dir.rglob("*.py"):
            if any(part in _EXCLUDE_PARTS for part in p.relative_to(repo_root).parts):
                continue
            seeds.add(p.resolve())
    return seeds


def _resolve_import(imp_module: str, from_file: Path, repo_root: Path,
                    file_index: dict[str, Path]) -> Path | None:
    """Resolve ``from ..services import helper`` etc. to an absolute file path.

    Returns None for stdlib / third-party imports (not found in repo).
    """
    if imp_module.startswith("."):
        level = len(imp_module) - len(imp_module.lstrip("."))
        tail = imp_module[level:]
        # from_file is repo_root/a/b/c.py; parent = repo_root/a/b; level=2 → repo_root/a
        base = from_file.parent
        for _ in range(level - 1):
            if base == repo_root.parent:
                return None
            base = base.parent
        if not tail:
            # `from . import X` — can't disambiguate without inspecting what's imported
            return base / "__init__.py" if (base / "__init__.py").is_file() else None
        candidates = [
            base / Path(*tail.split(".")).with_suffix(".py"),
            base / Path(*tail.split(".")) / "__init__.py",
        ]
        for c in candidates:
            if c.is_file():
                return c.resolve()
        return None
    # Absolute dotted path — look up in the index.
    return file_index.get(imp_module)


def _reachable_files(seeds: set[Path], repo_root: Path,
                     file_index: dict[str, Path]) -> set[Path]:
    """BFS from ``seeds`` over imports, staying inside ``repo_root``.

    For ``from X import a, b`` we also try resolving ``X.a`` and ``X.b`` as
    submodules — otherwise we'd only catch the package __init__ and miss the
    actual files the handler depends on (common in ``from ..services import
    aws_clients`` style imports).
    """
    seen: set[Path] = set(seeds)
    frontier = list(seeds)

    def _candidate_imports(py: Path):
        src = py.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(src, filename=str(py))
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield alias.name
            elif isinstance(node, ast.ImportFrom):
                level = "." * (node.level or 0)
                base = (node.module or "")
                root_mod = f"{level}{base}"
                yield root_mod
                # Each imported name might itself be a submodule.
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    sep = "" if not base and level else "."
                    yield f"{root_mod}{sep}{alias.name}"

    while frontier:
        f = frontier.pop()
        for imp_module in _candidate_imports(f):
            tgt = _resolve_import(imp_module, f, repo_root, file_index)
            if tgt is None or tgt in seen:
                continue
            try:
                tgt.relative_to(repo_root)
            except ValueError:
                continue
            seen.add(tgt)
            frontier.append(tgt)
    return seen


def _library_node_id(rel: Path) -> str:
    """Stable resource-id for a shared library file, e.g. 'services.helper'."""
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else str(rel)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
