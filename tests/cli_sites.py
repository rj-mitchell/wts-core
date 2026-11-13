"""The four sites as the command-line tests see them: each one's own names and words for the shared commands (what
its ``site.py`` will pass to ``wts_core.cli`` when it adopts the package), and how its own command line is loaded
from its checkout and run beside the package's, so the two can be compared line for line.

The words here are copied from each site's ``cli.py`` of the branch ``claude/gallant-cerf-xxy2ge``; the comparisons
in ``test_cli_ops.py`` and ``test_cli_replies.py`` are what keep them true.
"""

from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from typer.testing import CliRunner

from test_ops_sites import COUNCILS, COUNTRIES, LANDLORDS, MPS, SENTENCES, SiteFacts, checkout_of, frozen
from wts_core.cli import BackupCheckWords, BackupWords, OpsWording, RestoreWords

# ---- each site's words for its backup commands ---------------------------------------------------------------------

_OFFSITE_HELP = ("Check the off-site backup bucket: whether the key works, and how many of this site's backups "
                 "are there.")

OPS: dict[str, OpsWording] = {
    MPS.repo: OpsWording(
        backup=BackupWords(
            folder="backups", keep=14, nothing_to_back_up="Nothing to back up yet: there is no state database.",
            backed_up="Backed up to {archive}", failed=None,
            offsite_stored="Off-site copy: stored in {bucket} ({stored} kept there)",
            offsite_not_set_up="Off-site copy: not set up", offsite_failed="The off-site copy failed: {error}",
            to_help="folder for backups (default: <data>/backups)", keep_help="how many daily backups to keep"),
        restore=RestoreWords(
            archive_must_exist=True, says_aborted=True,
            confirm="This replaces the current saved briefings, reports and usage records. Continue?",
            restored="Restored. Start the site again.", replaced=" The database it replaced is kept as {kept}.",
            not_restored="Not restored: {error}", yes_help="do not ask for confirmation"),
        backup_check=None, errors_to_stderr=True,
        offsite_help="Check the off-site backup bucket: whether the key works, and how many backups are stored "
                     "there."),
    COUNTRIES.repo: OpsWording(
        backup=BackupWords(
            folder=None, keep=14, nothing_to_back_up="nothing to back up yet (no state database)",
            backed_up="backup: {archive}", failed=None,
            offsite_stored="Off-site copy: stored in {bucket} ({stored} kept there)",
            offsite_not_set_up="Off-site copy: not set up", offsite_failed="The off-site copy failed: {error}",
            to_help="folder for the backups", keep_help="how many to keep"),
        restore=RestoreWords(
            archive_must_exist=False, says_aborted=False,
            confirm="Replace {state_db} with {archive}? Stop the site first.",
            restored="restored {state_db} from {archive}", replaced="; the database it replaced is {kept}",
            not_restored="Not restored: {error}", yes_help="don't ask first",
            archive_help="a backup: /backups/wcs-state-YYYY-MM-DD.sqlite.gz"),
        backup_check=None, errors_to_stderr=True, offsite_help=_OFFSITE_HELP),
    COUNCILS.repo: OpsWording(
        backup=BackupWords(
            folder=None, keep=14, nothing_to_back_up="nothing to back up yet (no state database)",
            backed_up="backup: {archive}", failed=None,
            offsite_stored="Off-site copy: stored in {bucket} ({stored} kept there)",
            offsite_not_set_up="Off-site copy: not set up", offsite_failed="The off-site copy failed: {error}",
            to_help="folder for the backups", keep_help="how many to keep"),
        restore=None,
        backup_check=BackupCheckWords(
            folder="/backups", no_folder="error: there is no backup folder at {folder}", alert="{level}: {text}",
            up_to_date="Backups are up to date.", alerts=SENTENCES,
            folder_help="the folder the backups are written to"),
        errors_to_stderr=True, offsite_help=_OFFSITE_HELP),
    LANDLORDS.repo: OpsWording(
        backup=BackupWords(
            folder=None, keep=14, nothing_to_back_up="No state database yet: nothing to back up.",
            backed_up="Backed up to {archive} ({kept} kept)", failed="Backup failed: {error}",
            offsite_stored="Off-site copy: stored in {bucket}", offsite_not_set_up="Off-site copy: not set up",
            offsite_failed="Off-site copy failed: {error}", to_help="folder for the copies"),
        restore=None, backup_check=None, errors_to_stderr=False, offsite_help=_OFFSITE_HELP),
}


# ---- a site's own command line, from its checkout -----------------------------------------------------------------


def their_modules(facts: SiteFacts, request: pytest.FixtureRequest, *names: str) -> list[ModuleType]:
    """Modules of the site's own, loaded from its checkout for this one test (``<package>.cli`` and so on).

    The site is not installed. A stand-in for its package, holding nothing but the folder its modules are in, lets
    its modules import one another; everything of the site's is taken out of ``sys.modules`` again when the test
    ends. Nothing is written into the checkout, not even compiled files."""
    checkout_of(facts)
    mine = [k for k in sys.modules if k == facts.package or k.startswith(facts.package + ".")]
    before = {k: sys.modules.pop(k) for k in mine}
    writes = sys.dont_write_bytecode

    def forget() -> None:
        for k in [k for k in sys.modules if k == facts.package or k.startswith(facts.package + ".")]:
            del sys.modules[k]
        sys.modules.update(before)
        sys.dont_write_bytecode = writes

    request.addfinalizer(forget)
    sys.dont_write_bytecode = True
    package = ModuleType(facts.package)
    package.__path__ = [str(facts.src)]
    sys.modules[facts.package] = package
    try:
        return [importlib.import_module(f"{facts.package}.{name}") for name in names]
    except ImportError as exc:  # a module of the site's that needs a library this package's tests don't install
        pytest.skip(f"{facts.name}'s own code could not be loaded from {facts.checkout}: {exc}")


def stop_their_clock(monkeypatch: pytest.MonkeyPatch, when: datetime, *modules: ModuleType) -> None:
    """Make ``datetime.now()`` say ``when`` in each of a site's modules, which read the clock themselves."""
    for module in modules:
        monkeypatch.setattr(module, "datetime", frozen(when))


def mounted(commands: Any) -> Any:
    """The package's commands as a site has them: added to an app of its own, beside a command of its own."""
    import typer

    app = typer.Typer(add_completion=False, no_args_is_help=True)

    @app.callback()
    def main(verbose: bool = False) -> None: ...

    @app.command()
    def serve() -> None: ...

    app.add_typer(commands)
    return app


@pytest.fixture
def logging_left_as_it_was() -> Iterator[None]:
    """Every site's command line sets up logging when a command runs, to a stream that is gone when the run ends:
    what it added is taken away again."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in [h for h in root.handlers if h not in handlers]:
        root.removeHandler(handler)
    root.setLevel(level)


@dataclass(frozen=True)
class Said:
    """What one run of a command printed, and how it ended. Paths under the run's own folder are written
    ``<root>``, so that a site's run and the package's, each in its own folder, can be compared."""

    exit_code: int
    stdout: str
    stderr: str
    error: str | None  # an error that was not caught: its class and message (the traceback the owner would see)

    def __str__(self) -> str:
        return f"exit {self.exit_code}\n--- stdout\n{self.stdout}--- stderr\n{self.stderr}--- error\n{self.error}\n"


def run(app: Any, args: list[str], root: Path, *, answer: str | None = None, env: dict[str, str] | None = None) -> Said:
    result = CliRunner().invoke(app, [str(a) for a in args], input=answer, env=env)
    error = None
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        error = f"{type(result.exception).__name__}: {result.exception}"

    def rooted(text: str) -> str:
        return text.replace(str(root), "<root>")

    return Said(result.exit_code, rooted(result.stdout), rooted(result.stderr), rooted(error) if error else None)


def options(app: Any, name: str) -> dict[str, tuple[Any, ...]]:
    """A command's options and arguments as the owner meets them: each one's names, whether it must be given, what
    it is when it is not, and its help. Read from the command itself, not from the help page as drawn (whose boxes
    differ from one terminal to another)."""
    import typer

    command: Any = typer.main.get_command(app)
    for part in name.split():
        command = command.commands[part]
    return {p.name: (tuple(p.opts), p.required, None if callable(p.default) else p.default, getattr(p, "help", None))
            for p in command.params}
