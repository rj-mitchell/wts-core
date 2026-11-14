"""The family's toolchain is written once, in toolchain.toml, and the shared workflows and actions agree with it."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = tomllib.loads((ROOT / "toolchain.toml").read_text())
FILES = sorted((ROOT / ".github").rglob("*.yml"))


def defaults(text: str, name: str) -> set[str]:
    """Every default given to an input called ``name``."""
    return set(re.findall(rf"^\s+{re.escape(name)}:\n(?:\s+(?:description|type|required): .*\n)*\s+default: \"([^\"]*)\"",
                          text, re.M))


def test_there_are_shared_workflows_to_check():
    assert {p.name for p in FILES} >= {"python.yml", "web.yml", "kit.yml", "docker.yml", "ci.yml", "release.yml"}


def test_input_defaults_are_the_toolchains():
    for path in FILES:
        text = path.read_text()
        for name in ("python", "uv", "node", "playwright", "axe-core"):
            given = defaults(text, name) - {""}  # "" means "this job needs none"
            assert given <= {TOOLS[name]}, f"{path.relative_to(ROOT)}: {name} defaults to {sorted(given)}"


def test_versions_written_inline_are_the_toolchains():
    for path in FILES:
        text = path.read_text()
        for version in re.findall(r"setup-uv@\S+\n\s+with:\n\s+version: \"([\d.]+)\"", text):
            assert version == TOOLS["uv"], f"{path.relative_to(ROOT)}: uv {version}"
        for version in re.findall(r"uv==([\d.]+)", text):
            assert version == TOOLS["uv"], f"{path.relative_to(ROOT)}: uv {version}"


def test_actions_are_at_the_toolchains_versions():
    for path in FILES:
        for action, version in re.findall(r"uses: ([\w-]+/[\w-]+)@(\S+)", path.read_text()):
            if action in TOOLS["actions"]:
                assert version == TOOLS["actions"][action], f"{path.relative_to(ROOT)}: {action}@{version}"
            else:
                raise AssertionError(f"{path.relative_to(ROOT)} uses {action}, which toolchain.toml does not list")


def test_the_shared_python_checks_turn_typers_colour_off():
    """On GitHub Actions Typer draws ``--help`` with colour codes, which split an option's name: a site's test
    that reads a command's help passed on a developer's machine and failed in CI (the package's own first run did,
    and so did the first site's). The shared workflow turns it off once, for every site."""
    text = (ROOT / ".github" / "workflows" / "python.yml").read_text()
    for step in ("Lint", "Type check", "Tests"):
        block = text.split(f"      - name: {step}\n", 1)[1].split("      - name:", 1)[0]
        assert '_TYPER_FORCE_DISABLE_TERMINAL: "1"' in block and 'NO_COLOR: "1"' in block, step
    assert text.count('UV_NO_SYNC: "1"') == 2  # where it was: the type check and the tests
