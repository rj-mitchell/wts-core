"""The walls the design draws (docs/adr/0001, 0008) are tested, not just drawn.

Imports are read from the source of every module: ``import`` statements wherever they stand (inside a function
too), relative ones resolved, and calls to ``importlib.import_module`` and ``__import__`` with a name written out.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "wts_core"

# Outside the adapters a module may import the standard library and this package, and nothing else. The two
# exceptions are named, with why.
MAY_IMPORT = {
    "adapters": {"anthropic", "fastembed", "lancedb", "duckdb", "httpx", "numpy", "pyarrow", "pydantic"},
    "cli": {"typer"},  # the command line's own library, imported only when a command group is built
    "testing/contracts.py": {"pytest"},  # the contract tests are classes for pytest
}

# The right of reply shares nothing with what touches the model, the index or the record. Only these files may
# import ``wts_core.replies``: its own, the owner's commands for it, the nightly check's count of what is waiting,
# and the test helper that proves statements stay out. None of them passes a statement on.
MAY_IMPORT_REPLIES = {"cli/replies.py", "cli/check.py", "testing/privacy.py"}
NEAR_THE_MODEL = ("checks", "briefing", "observe", "eval", "adapters", "usage")


def imports(path: Path) -> set[str]:
    """Every module this file imports, by its full name."""
    package = ("wts_core", *path.relative_to(SRC).parts[:-1])
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = ".".join(package[:len(package) - node.level + 1])
                module = f"{base}.{node.module}" if node.module else base
                found.add(module)
                found |= {f"{module}.{a.name}" for a in node.names}  # ``from . import replies``
            elif node.module:
                found.add(node.module)
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name in ("import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant):
                found.add(str(node.args[0].value))
    return found


def where(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def area(path: Path) -> str:
    return path.relative_to(SRC).parts[0].removesuffix(".py")


def test_outside_the_adapters_only_the_standard_library_is_imported():
    for path in sorted(SRC.rglob("*.py")):
        outside = {name.split(".")[0] for name in imports(path)} - set(sys.stdlib_module_names) - {"wts_core"}
        allowed = MAY_IMPORT.get(area(path), set()) | MAY_IMPORT.get(where(path), set())
        assert outside <= allowed, f"{where(path)} imports {sorted(outside - allowed)}"


def test_ports_and_events_import_nothing_else_from_the_package():
    assert not {n for n in imports(SRC / "ports.py") if n.startswith("wts_core")} - {"wts_core.events"}
    assert {n for n in imports(SRC / "events.py") if n.startswith("wts_core")} <= {"wts_core.ports"}


def test_replies_shares_no_import_with_anything_that_touches_the_model_the_index_or_the_record():
    """Half of how statements under the right of reply never reach the model, the search index or the record
    (the other half is ``testing.assert_statements_stay_out``, run by each site against its own pipeline)."""
    near = tuple(f"wts_core.{name}" for name in NEAR_THE_MODEL)
    for path in sorted(SRC.rglob("*.py")):
        names = imports(path)
        if area(path) == "replies":
            assert {n for n in names if n.startswith("wts_core")} <= {
                "wts_core.ports", "wts_core.state", *(n for n in names if n.startswith("wts_core.replies"))
            }, f"{where(path)} imports {sorted(names)}"
            assert not [n for n in names if n.startswith(near)]
        elif [n for n in names if n.startswith("wts_core.replies")]:
            assert where(path) in MAY_IMPORT_REPLIES, f"{where(path)} imports the right of reply"


def test_the_files_that_may_import_replies_are_all_still_there_and_still_do():
    """So the list above cannot quietly hold a name nothing uses."""
    for name in MAY_IMPORT_REPLIES:
        assert [n for n in imports(SRC / name) if n.startswith("wts_core.replies")], name


def test_loading_what_is_near_the_model_never_loads_the_right_of_reply():
    """What the source says, checked against what Python does: with each of these loaded in a fresh interpreter,
    ``wts_core.replies`` is not among the modules loaded (a lazy or indirect import would show here)."""
    for module in ("wts_core.checks", "wts_core.briefing", "wts_core.observe", "wts_core.eval", "wts_core.usage",
                   "wts_core.testing", "wts_core.testing.models", "wts_core.testing.index"):
        code = (f"import sys, {module}\n"
                "loaded = sorted(m for m in sys.modules if m.startswith('wts_core.replies'))\n"
                "sys.exit(', '.join(loaded) or 0)")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
        assert done.returncode == 0, f"{module} loads {done.stderr.strip()}"
