"""The backup commands every site carries, for a site to add to its own command line.

``ops_commands`` gives ``backup`` and ``offsite`` and, where the site's ``OpsWording`` has words for them,
``restore`` and ``backup-check``. They are the commands the four sites each wrote out (docs/study/ops.md,
section 5), over ``wts_core.ops``::

    app.add_typer(ops_commands(SITE, load_settings, SPEC, WORDING))

What the four differ in is all in the wording a site passes: whether ``--to`` must be given, every line printed,
whether a failure is said on standard error (Where Landlords Stand says its on standard output) and whether a
backup that could not be made is said in a line or left as the error it is. The package prints no line of its own,
with one exception: when off-site copies are set up but the library that speaks to the store is not installed, it
says what to install.

Typer is imported when the commands are built, so ``wts_core.cli`` can be imported without it.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from wts_core.ops import (
    AlertWording,
    BackupSpec,
    OffsiteError,
    backup_alerts,
    check_offsite,
    make_backup,
    restore_backup,
    send_offsite,
)
from wts_core.ports import SYSTEM_CLOCK, Clock, OffsiteStore
from wts_core.settings import Settings, Site

if TYPE_CHECKING:
    import typer

__all__ = ["BackupCheckWords", "BackupWords", "OpsWording", "RestoreWords", "ops_commands"]


@dataclass(frozen=True, kw_only=True)
class BackupWords:
    """A site's ``backup`` command: its options and every line it prints."""

    # the folder under the data folder that backups go to when --to is not given ("backups" on Where MPs Stand);
    # None: --to must be given, as on the other three
    folder: str | None
    keep: int  # what --keep is when it is not given: 14 on all four, whatever each site's timer passes
    nothing_to_back_up: str  # there is no state database yet (a new site); exit 0
    backed_up: str  # {archive}: the file written; {kept}: how many of the site's archives are now in the folder
    # {error}: the copy could not be made or failed its check. None: the error is raised as it is, as on three of
    # the sites; Where Landlords Stand says it in a line and exits 1
    failed: str | None
    offsite_stored: str  # {bucket}, {stored}: how many of the site's copies are there now
    offsite_not_set_up: str
    offsite_failed: str  # {error}; exit 1, the local backup having been made
    name: str = "backup"
    help: str | None = None  # the command's own description, and its options'
    to_help: str | None = None
    keep_help: str | None = None


@dataclass(frozen=True, kw_only=True)
class RestoreWords:
    """A site's ``restore`` command (Where MPs Stand and Where Countries Stand have one)."""

    archive_must_exist: bool  # Where MPs Stand: Typer refuses a path that is not a file before anything is asked
    confirm: str  # the question asked without --yes; {state_db}, {archive}
    says_aborted: bool  # "no" prints Typer's "Aborted." (Where MPs Stand), or nothing; exit 1 either way
    restored: str  # {state_db}, {archive}
    replaced: str  # added to ``restored`` when a database was replaced; {kept}: where it is kept
    not_restored: str  # {error}: the reason, from ``ops.RestoreRefused`` or the operating system; exit 1
    name: str = "restore"
    help: str | None = None
    archive_help: str | None = None
    yes_help: str | None = None


@dataclass(frozen=True, kw_only=True)
class BackupCheckWords:
    """A site's ``backup-check`` command (Where Councils Stand's): the alerts of ``ops.backup_alerts``, printed, and
    exit 1 if any is an error."""

    folder: str  # what --in is when it is not given: "/backups"
    no_folder: str  # {folder}; exit 1
    alert: str  # {level}, {text}: one line for each alert
    up_to_date: str
    alerts: AlertWording
    name: str = "backup-check"
    help: str | None = None
    folder_help: str | None = None


@dataclass(frozen=True, kw_only=True)
class OpsWording:
    """Everything a site's backup commands are called and say. ``restore`` and ``backup_check`` are None on a site
    that has no such command."""

    backup: BackupWords
    restore: RestoreWords | None
    backup_check: BackupCheckWords | None
    errors_to_stderr: bool  # where a failure is said: standard error, or (Where Landlords Stand) standard output
    offsite_name: str = "offsite"
    offsite_help: str | None = None


def ops_commands(site: Site, settings: Callable[[], Settings], spec: BackupSpec, wording: OpsWording, *,
                 store: Callable[[], OffsiteStore | None] | None = None, how_to_set_up: str | None = None,
                 env: Mapping[str, str] | None = None, clock: Clock = SYSTEM_CLOCK,
                 before: Callable[[], None] | None = None) -> typer.Typer:
    """The site's backup commands, to add to its own app with ``app.add_typer(...)`` (no name: they join the
    site's other commands).

    ``settings`` is called when a command runs, never when the commands are built; the state database is its
    ``state_db``. ``store`` gives the off-site store, or None when none is set up: left out, it is the site's
    Backblaze B2 bucket (``adapters.b2.configured(site, env)``), and ``how_to_set_up`` is then that adapter's own
    sentence; a site with another store gives both. How many copies stay off site is the spec's ``keep_offsite``.
    ``before`` is called first in every command (Where MPs Stand sets up its logging there)."""
    import typer

    app = typer.Typer(add_completion=False)
    words = wording.backup

    def say(line: str, *, error: bool = False) -> None:
        typer.echo(line, err=error and wording.errors_to_stderr)

    def start() -> None:
        if before is not None:
            before()

    def offsite_store() -> OffsiteStore | None:
        if store is not None:
            return store()
        from wts_core.adapters import b2

        return b2.configured(site, env)

    def setting_up() -> str | None:
        if store is not None:
            return how_to_set_up
        from wts_core.adapters import b2

        return how_to_set_up or b2.how_to_set_up(site)

    @contextmanager
    def library_needed() -> Iterator[None]:
        """The store's adapter imports its library when it is first used: a site that has set up off-site copies
        without installing it is told what to install, not shown a traceback."""
        try:
            yield
        except ModuleNotFoundError as exc:
            typer.echo(f"Off-site copies are set up, but the library that sends them ({exc.name}) is not installed: "
                       "add the extra to the site's dependencies, wts-core[offsite].", err=True)
            raise typer.Exit(1) from exc

    to_option = typer.Option(None if words.folder is not None else ..., "--to", help=words.to_help)
    keep_option = typer.Option(words.keep, "--keep", help=words.keep_help)

    @app.command(words.name, help=words.help)
    def backup(to: Path | None = to_option, keep: int = keep_option) -> None:
        start()
        loaded = settings()
        dest = to if to is not None else loaded.data_dir / (words.folder or "")
        try:
            archive = make_backup(loaded.state_db, dest, spec, keep=keep, clock=clock)
        except (RuntimeError, sqlite3.Error) as exc:  # the copy can't be trusted: nothing is kept or sent off site
            if words.failed is None:
                raise
            say(words.failed.format(error=exc), error=True)
            raise typer.Exit(1) from exc
        if archive is None:
            say(words.nothing_to_back_up)
            return
        say(words.backed_up.format(archive=archive, kept=len(spec.archives(dest))))
        try:  # and a copy off the server, when a store is set up
            with library_needed():
                sent = send_offsite(archive, offsite_store(), spec, clock=clock)
        except OffsiteError as exc:
            say(words.offsite_failed.format(error=exc), error=True)
            raise typer.Exit(1) from exc
        say(words.offsite_stored.format(bucket=sent["bucket"], stored=sent["stored"]) if sent.get("ok")
            else words.offsite_not_set_up)

    @app.command(wording.offsite_name, help=wording.offsite_help)
    def offsite() -> None:
        start()
        with library_needed():
            answer = check_offsite(offsite_store(), spec, how_to_set_up=setting_up())
        typer.echo(json.dumps(answer, indent=2))

    if wording.restore is not None:
        restoring = wording.restore
        archive_argument = typer.Argument(..., exists=restoring.archive_must_exist,
                                          dir_okay=not restoring.archive_must_exist, help=restoring.archive_help)
        yes_option = typer.Option(False, "--yes", help=restoring.yes_help)

        @app.command(restoring.name, help=restoring.help)
        def restore(archive: Path = archive_argument, yes: bool = yes_option) -> None:
            start()
            state_db = settings().state_db
            if not yes and not typer.confirm(restoring.confirm.format(state_db=state_db, archive=archive),
                                             abort=restoring.says_aborted):
                raise typer.Exit(1)
            try:
                kept = restore_backup(archive, state_db, spec)
            except (OSError, RuntimeError) as exc:
                say(restoring.not_restored.format(error=exc), error=True)
                raise typer.Exit(1) from exc
            say(restoring.restored.format(state_db=state_db, archive=archive)
                + (restoring.replaced.format(kept=kept) if kept else ""))

    if wording.backup_check is not None:
        checking = wording.backup_check
        folder_option = typer.Option(checking.folder, "--in", help=checking.folder_help)

        @app.command(checking.name, help=checking.help)
        def backup_check(folder: Path = folder_option) -> None:
            start()
            if not folder.is_dir():
                say(checking.no_folder.format(folder=folder), error=True)
                raise typer.Exit(1)
            alerts = backup_alerts(folder, spec, offsite_set_up=offsite_store() is not None, wording=checking.alerts,
                                   clock=clock)
            for alert in alerts:
                say(checking.alert.format(level=alert.level, text=alert.text), error=alert.level == "error")
            if not alerts:
                say(checking.up_to_date)
            if any(alert.level == "error" for alert in alerts):
                raise typer.Exit(1)

    return app
