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


def _offenders(package_dir: Path, forbidden_prefixes: tuple[str, ...]) -> list[str]:
    out = []
    for py in package_dir.rglob("*.py"):
        for m in _imported_modules(py):
            if any(m == p or m.startswith(p + ".") for p in forbidden_prefixes):
                out.append(f"{py.relative_to(SRC)} imports {m}")
    return out


def test_clarion_never_imports_clarion_web():
    offenders = _offenders(SRC / "clarion", ("clarion_web",))
    assert not offenders, f"clarion must not depend on clarion_web: {offenders}"


def test_db_imports_no_domain():
    offenders = _offenders(
        SRC / "clarion" / "db",
        ("clarion.ingest", "clarion.digest", "clarion.catalog", "clarion_web"),
    )
    assert not offenders, f"db must stay domain-free: {offenders}"


def test_web_imports_only_the_sanctioned_surface():
    """The web app reaches clarion only through db, the stream registry,
    the flat utilities, and digest.text (dependency-free display helpers)."""
    allowed = (
        "clarion.config",
        "clarion.db",
        "clarion.digest.text",
        "clarion.ingest.sources",
        "clarion.logging",
        "clarion.timeutils",
    )
    offenders = []
    for py in (SRC / "clarion_web").rglob("*.py"):
        for m in _imported_modules(py):
            if m != "clarion" and not m.startswith("clarion."):
                continue
            if not any(m == a or m.startswith(a + ".") for a in allowed):
                offenders.append(f"{py.relative_to(SRC)} imports {m}")
    assert not offenders, f"web must use the sanctioned surface only: {offenders}"


def test_domains_do_not_import_each_other():
    """One sanctioned exception: clarion.ingest.sources is the stream-type
    contract (config schemas + registry) shared by catalog (writes stream
    rows), the web (validates forms), and the collector (runs streams).
    If the repo ever splits into distributions, that subpackage moves to
    the shared core."""
    domains = ("ingest", "digest", "catalog")
    offenders = []
    for d in domains:
        others = tuple(f"clarion.{o}" for o in domains if o != d)
        offenders += [
            o for o in _offenders(SRC / "clarion" / d, others)
            if "clarion.ingest.sources" not in o
        ]
    assert not offenders, f"domains must not import each other: {offenders}"
