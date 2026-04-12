"""
Architecture checker — enforce one-way layered dependency rules.

Layer hierarchy (strict): Types → Config → Repository → Service → API → UI
A layer can ONLY import from layers below it.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

LAYER_RANKS = {
    "types": 0, "models": 0, "schemas": 0,
    "config": 1,
    "repository": 2, "db": 2, "persistence": 2,
    "service": 3, "domain": 3,
    "api": 4, "routes": 4, "handlers": 4,
    "ui": 5, "frontend": 5, "components": 5,
}

@dataclass
class ArchViolation:
    file: str
    line: int
    source_layer: str
    target_layer: str
    import_text: str

def check_architecture(project_root: str) -> list[ArchViolation]:
    """Scan all Python/JS files for upward import violations."""
    violations = []
    root = Path(project_root)

    for pattern in ["**/*.py", "**/*.js", "**/*.ts"]:
        for filepath in root.glob(pattern):
            # Skip test files and node_modules
            rel = str(filepath.relative_to(root))
            if "test" in rel.lower() or "node_modules" in rel or "__pycache__" in rel:
                continue

            # Determine this file's layer
            file_layer, file_rank = _get_layer(rel)
            if file_layer is None:
                continue

            # Check each import line
            try:
                for i, line in enumerate(filepath.read_text(errors="replace").split("\n"), 1):
                    stripped = line.strip()
                    if not (stripped.startswith("from ") or stripped.startswith("import ")):
                        continue
                    for target_layer, target_rank in LAYER_RANKS.items():
                        if target_rank > file_rank:
                            if re.search(rf'\b{target_layer}\b', stripped):
                                violations.append(ArchViolation(
                                    file=rel, line=i,
                                    source_layer=file_layer, target_layer=target_layer,
                                    import_text=stripped[:100],
                                ))
            except Exception:
                continue
    return violations

def _get_layer(path: str) -> tuple[str | None, int]:
    for layer, rank in LAYER_RANKS.items():
        if f"/{layer}/" in f"/{path}":
            return layer, rank
    return None, 99
