"""The walls the design draws (docs/adr/0001, 0008) are tested, not just drawn."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "wts_core"
OUTSIDE = {"anthropic", "fastembed", "lancedb", "duckdb", "httpx", "numpy", "pyarrow", "typer", "fastapi", "starlette",
           "pydantic", "uvicorn"}
# typer is the command line's own library: only wts_core.cli may import it
ALLOWED = {"adapters": OUTSIDE - {"typer", "fastapi", "starlette", "uvicorn"}, "cli": {"typer"}}


def imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def area(path: Path) -> str:
    rel = path.relative_to(SRC)
    return rel.parts[0].removesuffix(".py")


def test_only_the_adapters_import_an_outside_library():
    for path in sorted(SRC.rglob("*.py")):
        used = {name.split(".")[0] for name in imports(path)} & OUTSIDE
        assert used <= ALLOWED.get(area(path), set()), f"{path.relative_to(SRC)} imports {sorted(used)}"


def test_ports_and_events_import_nothing_else_from_the_package():
    assert not {n for n in imports(SRC / "ports.py") if n.startswith("wts_core")} - {"wts_core.events"}
    assert {n for n in imports(SRC / "events.py") if n.startswith("wts_core")} <= {"wts_core.ports"}


def test_replies_shares_no_import_with_anything_that_touches_the_model_the_index_or_the_record():
    """Half of how statements under the right of reply never reach the model, the search index or the record."""
    near_the_model = ("wts_core.checks", "wts_core.briefing", "wts_core.observe", "wts_core.eval", "wts_core.adapters")
    for path in sorted(SRC.rglob("*.py")):
        names = imports(path)
        if area(path) == "replies":
            assert not [n for n in names if n.startswith(near_the_model)], f"{path.relative_to(SRC)}: {sorted(names)}"
        elif area(path) in ("checks", "briefing", "observe", "eval", "adapters"):
            assert not [n for n in names if n.startswith("wts_core.replies")], f"{path.relative_to(SRC)}"
