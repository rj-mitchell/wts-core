"""The public interface cannot change silently (docs/adr/0007-versioning.md).

The interface is exactly what ``wts_core.__all__`` and each module's ``__all__`` export. Its names and signatures
are written to ``docs/api-snapshot.txt``; this test fails when the code and the snapshot differ, and when the
snapshot's fingerprint is not the ``api:`` line under the newest version in ``CHANGELOG.md``. So every change to
the interface is written down where the sites will read it.

To accept a change: ``WTS_UPDATE_API=1 uv run pytest tests/test_public_api.py``, then put the fingerprint it
prints on the ``api:`` line of the changelog, beside an entry saying what changed and what a site must do.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import importlib
import inspect
import os
import pkgutil
import re
import typing
from pathlib import Path
from typing import Any

import wts_core

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "docs" / "api-snapshot.txt"
CHANGELOG = ROOT / "CHANGELOG.md"
_ADDRESS = re.compile(r" at 0x[0-9a-f]+")


def _signature(thing: Any) -> str:
    try:
        return _ADDRESS.sub("", str(inspect.signature(thing)))
    except (TypeError, ValueError):
        return "(...)"


def _value(value: Any) -> str:
    if isinstance(value, str | int | float | bool | type(None)):
        return repr(value)
    if isinstance(value, tuple | frozenset | list | set | dict):
        return f"{type(value).__name__} of {len(value)}"
    return type(value).__name__


def _class(name: str, cls: type) -> list[str]:
    bases = ", ".join(b.__name__ for b in cls.__bases__ if b is not object)
    lines = [f"class {name}({bases})" if bases else f"class {name}"]
    if dataclasses.is_dataclass(cls):
        for f in dataclasses.fields(cls):
            default = "" if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING else " = ..."
            lines.append(f"    {f.name}: {f.type}{default}")
    elif issubclass(cls, enum.Enum):
        lines += [f"    {member.name} = {member.value!r}" for member in cls]
    for attr, member in sorted(vars(cls).items()):
        if attr.startswith("_") and attr not in ("__init__", "__call__", "__add__"):
            continue
        if attr == "__init__" and dataclasses.is_dataclass(cls):
            continue
        if isinstance(member, staticmethod | classmethod):
            lines.append(f"    {type(member).__name__} {attr}{_signature(member.__func__)}")
        elif isinstance(member, property):
            lines.append(f"    property {attr}")
        elif inspect.isfunction(member):
            lines.append(f"    def {attr}{_signature(member)}")
    return lines


def _describe(name: str, thing: Any) -> list[str]:
    if inspect.isclass(thing):
        return _class(name, thing)
    if inspect.isfunction(thing):
        return [f"def {name}{_signature(thing)}"]
    if isinstance(thing, typing.TypeAliasType):
        return [f"type {name} = {thing.__value__}"]
    if name == "__version__":
        return ["__version__ = <the version>"]  # it changes with every release; the interface does not
    return [f"{name} = {_value(thing)}"]


def interface() -> str:
    lines: list[str] = []
    modules = ["wts_core", *sorted(m.name for m in pkgutil.walk_packages(wts_core.__path__, "wts_core."))]
    for module_name in modules:
        module = importlib.import_module(module_name)
        names = getattr(module, "__all__", None)
        if names is None:
            continue
        lines.append(f"## {module_name}")
        for name in sorted(names):
            thing = getattr(module, name)  # a name in __all__ that is not there is an error worth failing on
            home = getattr(thing, "__module__", module_name)
            if home != module_name and str(home).startswith("wts_core") and not isinstance(thing, str | int | tuple):
                lines.append(f"{name}: from {home}")  # exported again from where it lives: described once, there
            else:
                lines += _describe(name, thing)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def test_the_public_interface_is_the_one_written_down():
    now = interface()
    if os.environ.get("WTS_UPDATE_API"):
        SNAPSHOT.write_text(now)
        print(f"\napi: {fingerprint(now)}")
    assert SNAPSHOT.exists(), "docs/api-snapshot.txt is missing: see this file's docstring"
    assert now == SNAPSHOT.read_text(), (
        "the public interface differs from docs/api-snapshot.txt: if the change is meant, accept it as this "
        "file's docstring says and write it in CHANGELOG.md")


def test_a_change_to_the_interface_is_in_the_changelog():
    newest = re.search(r"^## .*?$(.*?)(?=^## |\Z)", CHANGELOG.read_text(), re.S | re.M)
    assert newest, "CHANGELOG.md has no version section"
    line = re.search(r"^api: ([0-9a-f]{12})$", newest.group(1), re.M)
    assert line, "the newest version in CHANGELOG.md has no `api: <fingerprint>` line"
    assert line.group(1) == fingerprint(SNAPSHOT.read_text()), (
        "docs/api-snapshot.txt has changed without the changelog saying so: write what changed under the newest "
        f"version and set its line to `api: {fingerprint(SNAPSHOT.read_text())}`")


def test_every_module_says_what_it_exports():
    """A module with no ``__all__`` would have no public names by the rule, which is never what was meant."""
    missing = []
    for m in pkgutil.walk_packages(wts_core.__path__, "wts_core."):
        module = importlib.import_module(m.name)
        public = [n for n, v in vars(module).items()
                  if not n.startswith("_") and getattr(v, "__module__", None) == m.name]
        if public and not hasattr(module, "__all__"):
            missing.append(m.name)
    assert not missing, f"no __all__ in: {', '.join(missing)}"
