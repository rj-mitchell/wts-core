"""Run with a Python that has only the wts-core wheel installed: every base module imports, and no outside library
came with it (docs/adr/0001-slices-and-module-boundaries.md). Used by CI's base-only job."""

from __future__ import annotations

import importlib
import importlib.metadata
import pkgutil
import sys

import wts_core

NOT_WANTED = {"anthropic", "fastembed", "lancedb", "numpy", "pyarrow", "duckdb", "httpx", "typer", "fastapi",
              "pydantic", "onnxruntime", "tokenizers"}
# the contract tests are classes for pytest, which a site's test environment has; everything else imports on
# its own: the commands import typer, and the adapters their libraries, only when used
NEEDS_AN_EXTRA = ("wts_core.testing.contracts",)

installed = {d.metadata["Name"].lower().replace("_", "-") for d in importlib.metadata.distributions()}
extra = sorted(installed & NOT_WANTED)
if extra:
    sys.exit(f"the base install brought: {', '.join(extra)}")

failed = []
for module in pkgutil.walk_packages(wts_core.__path__, "wts_core."):
    if module.name.startswith(NEEDS_AN_EXTRA):
        continue
    try:
        importlib.import_module(module.name)
    except Exception as exc:  # reported together, below
        failed.append(f"{module.name}: {type(exc).__name__}: {exc}")
if failed:
    sys.exit("these modules do not import on the base install:\n  " + "\n  ".join(failed))
print(f"wts-core {wts_core.__version__}: the base install imports cleanly; installed: {', '.join(sorted(installed))}")
