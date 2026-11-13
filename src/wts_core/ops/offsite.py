"""Off-site copies of the nightly backup, and the warnings when backups or copies have stopped.

``send_offsite`` stores one archive away from the server, deletes all but the newest ``keep`` of **this site's**
copies there (those whose names start with the spec's prefix: the charity's sites can share one bucket and key, and
each deletes only its own), and records the outcome in ``offsite.json`` beside the archive. ``check_offsite`` says
whether the store answers and what is in it. ``backup_alerts`` reads the backups folder and ``offsite.json`` and
says what the owner should know.

This is the ``offsite.py`` the four sites each carry, which are the same statements, speaking to
``ports.OffsiteStore`` rather than to Backblaze: the store is passed in, and None means off-site copies are not set
up. The alerts' wording is the site's own (``AlertWording``): Where MPs Stand's and Where Councils Stand's are
sentences, Where Countries Stand's follow "warning: backup:" in its update report. Nothing here ever sees a key.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from wts_core.ops.backup import BackupSpec
from wts_core.ports import SYSTEM_CLOCK, Clock, OffsiteError, OffsiteStore, OffsiteUnavailable, StoredFile

__all__ = ["Alert", "AlertWording", "OffsiteError", "OffsiteUnavailable", "backup_alerts", "check_offsite",
           "send_offsite"]

_log = logging.getLogger(__name__)

_STATUS_FILE = "offsite.json"


@dataclass(frozen=True)
class Alert:
    level: Literal["error", "warning"]
    text: str


@dataclass(frozen=True)
class AlertWording:
    """A site's own words for each thing ``backup_alerts`` can say. Each site supplies all of them."""

    no_backups: str  # "No backups have been made yet."
    backup_stale: str  # "The last backup was made over two days ago ({name})."  {name}: the newest archive's
    server_only: str  # "Backups are kept on this server only: no off-site copy is set up."
    no_offsite_yet: str  # "No off-site copy has been made yet; one is made with the next backup."
    offsite_failed: str  # "The last off-site copy failed ({when}): {error}"  {when}: to the minute
    offsite_stale: str  # "The last off-site copy was over two days ago ({day})."


def send_offsite(archive: Path, store: OffsiteStore | None, spec: BackupSpec, *, keep: int = 60,
                 clock: Clock = SYSTEM_CLOCK) -> dict[str, Any]:
    """Store one backup off site and delete this site's old copies there, keeping the newest ``keep`` (zero or less
    deletes nothing). The outcome is returned and written to ``offsite.json`` beside the archive. With no store the
    answer is ``{"offsite": "not set up"}`` and nothing is written. Raises OffsiteError, after recording the failure
    there, if the copy could not be stored."""
    archive = Path(archive)
    if store is None:
        return {"offsite": "not set up"}
    when = clock.now().isoformat(timespec="seconds")
    try:
        try:
            store.put(archive)
            try:
                pruned = _prune(store, spec.prefix, keep)
            except OffsiteUnavailable:
                raise
            except OffsiteError as exc:  # a key without delete rights still stores backups
                _log.warning("old off-site backups not deleted: %s", exc)
                pruned = 0
            stored = len(store.list(spec.prefix))
        finally:
            store.close()
    except OffsiteError as exc:
        _write_status(archive.parent, {"ok": False, "when": when, "error": str(exc)[:300]})
        raise OffsiteError(str(exc)) from exc
    status = {"ok": True, "when": when, "file": archive.name, "bucket": store.name, "stored": stored,
              "deleted": pruned}
    _write_status(archive.parent, status)
    return status


def check_offsite(store: OffsiteStore | None, spec: BackupSpec, *, how_to_set_up: str | None = None) -> dict[str, Any]:
    """Whether the store answers, and how many of this site's backups are in it (for a site's ``offsite`` command).
    With no store, ``ok`` is false and the error is "not set up", followed by ``how_to_set_up`` where the site gives
    it (``adapters.b2.how_to_set_up(site)`` names the three variables). Raises OffsiteError if the store refuses the
    key or cannot be reached."""
    if store is None:
        return {"ok": False, "error": "not set up" + (f": {how_to_set_up}" if how_to_set_up else "")}
    try:
        files = _oldest_first(store, spec.prefix)
    finally:
        store.close()
    return {"ok": True, "bucket": store.name, "backups": len(files), "newest": files[-1].name if files else None}


def backup_alerts(folder: Path, spec: BackupSpec, *, offsite_set_up: bool, wording: AlertWording,
                  stale_hours: int = 50, clock: Clock = SYSTEM_CLOCK) -> list[Alert]:
    """A nightly backup that has not run, or an off-site copy that failed or is old. Nothing when the folder is not
    there (a computer that makes no backups). "Newest" is by name; a backup's age is its file's modification time.
    A backup timer that has stopped running sends no failure of its own, so a site checks these every day and has
    an error emailed."""
    folder = Path(folder)
    now = clock.now()
    if not folder.is_dir():
        return []
    out: list[Alert] = []
    local = spec.archives(folder)
    if not local:
        out.append(Alert("warning", wording.no_backups))
    elif (now - datetime.fromtimestamp(local[-1].stat().st_mtime, UTC)).total_seconds() > stale_hours * 3600:
        out.append(Alert("error", wording.backup_stale.format(name=local[-1].name)))
    if not offsite_set_up:
        out.append(Alert("warning", wording.server_only))
        return out
    try:
        status = json.loads((folder / _STATUS_FILE).read_text())
    except (OSError, ValueError):
        status = None
    if local and status is None:
        out.append(Alert("warning", wording.no_offsite_yet))
    elif status and not status.get("ok"):
        # a record with no usable time (null, or a number) is still reported, not an exception
        out.append(Alert("error", wording.offsite_failed.format(when=str(status.get("when", ""))[:16],
                                                               error=status.get("error", ""))))
    elif status and (now - datetime.fromisoformat(status["when"])).total_seconds() > stale_hours * 3600:
        out.append(Alert("error", wording.offsite_stale.format(day=status["when"][:10])))
    return out


def _oldest_first(store: OffsiteStore, prefix: str) -> list[StoredFile]:
    # sorted here as well as by the store: the newest are the ones kept, whatever order a store answers in
    return sorted(store.list(prefix), key=lambda f: f.name)


def _prune(store: OffsiteStore, prefix: str, keep: int) -> int:
    old = _oldest_first(store, prefix)[:-keep] if keep > 0 else []
    for f in old:
        store.delete(f)
    return len(old)




def _write_status(dest: Path, status: dict[str, Any]) -> None:
    with contextlib.suppress(OSError):
        (dest / _STATUS_FILE).write_text(json.dumps(status))
