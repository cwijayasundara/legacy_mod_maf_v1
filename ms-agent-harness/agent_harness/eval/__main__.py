"""Eval CLI: python -m agent_harness.eval run|report ..."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from ..persistence.repository import MigrationRepository
from .corpus import load_corpus, CORPUS_ROOT
from .report import render
from .runner import run_corpus
from .scorers import inventory as inv_scorer
from .scorers import graph as graph_scorer
from .scorers import stories as stories_scorer
from .scorers import brd as brd_scorer
from .scorers import design as design_scorer


async def _run_one(corpus_name: str, tier: str, out_dir: Path) -> int:
    try:
        corpus = load_corpus(corpus_name)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    repo = MigrationRepository(db_path=out_dir / "_migration.db")
    repo.initialize()
    try:
        artifacts = await run_corpus(corpus=corpus, tier=tier, repo=repo)
    except Exception as exc:
        print(f"ERROR: pipeline crash: {exc!r}", file=sys.stderr)
        return 2

    results = [
        inv_scorer.score(artifacts.inventory, corpus.expected_inventory),
        graph_scorer.score(artifacts.graph, corpus.expected_graph),
        stories_scorer.score(artifacts.stories, corpus.expected_stories),
        await brd_scorer.score(artifacts.brd, corpus.expected_inventory, artifacts.graph),
        await design_scorer.score(artifacts.design, corpus.expected_inventory, artifacts.graph),
    ]
    bundle = render(results, corpus_name=corpus_name, tier=tier, out_dir=out_dir)
    print(f"Report: {bundle.run_dir}")
    return 0 if bundle.overall_passed else 1


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent_harness.eval")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("--corpus", default=None,
                        help="Corpus name under tests/eval_corpus/. Defaults to all.")
    p_run.add_argument("--tier", choices=["deterministic", "real_llm"],
                        default="real_llm")
    p_run.add_argument("--out", default="eval-results", type=Path)

    p_report = sub.add_parser("report")
    p_report.add_argument("run_dir", type=Path)

    ns = parser.parse_args(argv)

    if ns.cmd == "report":
        md = (ns.run_dir / "report.md")
        if not md.exists():
            print(f"ERROR: no report at {md}", file=sys.stderr)
            return 2
        print(md.read_text(encoding="utf-8"))
        return 0

    out_dir = Path(ns.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if ns.corpus:
        return await _run_one(ns.corpus, ns.tier, out_dir)

    overall = 0
    for entry in sorted(Path(CORPUS_ROOT).iterdir()):
        if not entry.is_dir():
            continue
        code = await _run_one(entry.name, ns.tier, out_dir)
        if code > overall:
            overall = code
    return overall


def _entrypoint() -> None:
    code = asyncio.run(main(sys.argv[1:]))
    raise SystemExit(code)


if __name__ == "__main__":
    _entrypoint()
