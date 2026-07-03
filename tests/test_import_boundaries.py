"""The dependency rule that keeps a future codebase split cheap:
`clarion` (collector, digest, catalog, db) must never import `clarion_web`."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def _imported_modules(path: Path) -> set[str]:
    out: set[str] = set()
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_clarion_never_imports_clarion_web():
    offenders = [
        str(py.relative_to(SRC))
        for py in (SRC / "clarion").rglob("*.py")
        if any(
            m == "clarion_web" or m.startswith("clarion_web.")
            for m in _imported_modules(py)
        )
    ]
    assert not offenders, f"clarion must not depend on clarion_web: {offenders}"
