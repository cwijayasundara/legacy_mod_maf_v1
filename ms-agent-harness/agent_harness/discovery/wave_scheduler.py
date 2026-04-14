"""Deterministic topological layering of stories into migration waves.

No LLM. Cycle = hard error naming the cycle members.
"""
from __future__ import annotations

from collections import defaultdict, deque

from .artifacts import Backlog, BacklogItem, Stories


class CycleError(ValueError):
    pass


def schedule(stories: Stories, language_by_module: dict[str, str]) -> Backlog:
    by_id = {s.id: s for s in stories.stories}

    for s in stories.stories:
        for dep in s.depends_on:
            if dep not in by_id:
                raise ValueError(f"Story {s.id} depends_on unknown story id: {dep}")

    indeg: dict[str, int] = {sid: 0 for sid in by_id}
    succ: dict[str, list[str]] = defaultdict(list)
    for s in stories.stories:
        for dep in s.depends_on:
            indeg[s.id] += 1
            succ[dep].append(s.id)

    epic_module: dict[str, str] = {e.id: e.module_id for e in stories.epics}

    layer_of: dict[str, int] = {}
    queue = deque(sorted(sid for sid, d in indeg.items() if d == 0))
    while queue:
        sid = queue.popleft()
        my_layer = max((layer_of[d] for d in by_id[sid].depends_on), default=0) + 1
        layer_of[sid] = my_layer
        for n in succ[sid]:
            indeg[n] -= 1
            if indeg[n] == 0:
                queue.append(n)

    if len(layer_of) != len(by_id):
        unresolved = sorted(set(by_id) - set(layer_of))
        raise CycleError(f"Cycle detected involving stories: {unresolved}")

    items: list[BacklogItem] = []
    for sid in sorted(by_id, key=lambda x: (layer_of[x], x)):
        s = by_id[sid]
        module = epic_module.get(s.epic_id, s.epic_id)
        ac = "\n".join(c.text for c in s.acceptance_criteria)
        items.append(BacklogItem(
            module=module,
            language=language_by_module.get(module, "python"),
            work_item_id=s.id,
            title=s.title,
            description=s.description,
            acceptance_criteria=ac,
            wave=layer_of[sid],
        ))
    return Backlog(items=items)
