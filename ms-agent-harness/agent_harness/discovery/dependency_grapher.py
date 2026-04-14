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


async def _run_agent(message: str) -> str:
    """LLM invocation seam — patched in tests."""
    agent = create_agent(role="dependency_grapher",
                         tools=[read_file, list_directory, search_files])
    return await run_with_retry(agent, message)


async def build_graph(repo_id: str, repo_root: Path,
                      inventory: Inventory,
                      extra_instructions: str = "") -> DependencyGraph:
    """Build the graph deterministically; invoke LLM only for ambiguous calls."""
    repo_root = Path(repo_root).resolve()
    builder = GraphBuilder()
    module_paths: dict[str, Path] = {}

    for m in inventory.modules:
        builder.add_module(m.id, attrs={"path": m.path, "language": m.language})
        module_paths[m.id] = repo_root / m.path

    module_ids = set(module_paths)
    ambiguous_calls: list[tuple[str, str]] = []

    for m in inventory.modules:
        for py_file in module_paths[m.id].rglob("*.py"):
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
        raw = await _run_agent(msg)
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


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        nl = text.find("\n")
        text = text[nl + 1 :] if nl != -1 else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
