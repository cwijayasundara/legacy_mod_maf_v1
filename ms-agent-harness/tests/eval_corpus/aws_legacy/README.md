# aws_legacy corpus

Placeholder expected files. Before this corpus gives meaningful regression signal:

1. Run once: `python -m agent_harness.eval run --corpus=aws_legacy --tier=real_llm`
2. Inspect the generated inventory / graph / stories under `discovery/eval-aws_legacy/`.
3. Hand-review and copy into `expected_inventory.json`, `expected_graph.json`,
   `expected_stories_shape.json`, replacing the placeholders above.
4. Author `canned/*` if you need a deterministic tier for this corpus.

Until step 3 is done, `expected_inventory.modules: []` makes every run trivially
pass the inventory/graph/stories scorers. That's intentional — the corpus is
staged but not yet wired as a regression gate.
