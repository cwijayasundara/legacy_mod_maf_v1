"""Evaluation framework for the discovery pipeline.

Public API:
- load_corpus(name) -> Corpus
- run_corpus(corpus, tier, repo) -> RunArtifacts
- render(results, corpus_name, tier, out_dir) -> ReportBundle
"""
from .corpus import Corpus, load_corpus
from .report import ReportBundle, render
from .runner import RunArtifacts, run_corpus

__all__ = [
    "Corpus", "load_corpus",
    "RunArtifacts", "run_corpus",
    "ReportBundle", "render",
]
