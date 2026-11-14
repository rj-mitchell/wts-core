"""The record of each briefing, kept in a site's state database (ADR 0012), and the two small tables beside it.

- ``wts_briefing_log``: one row a question asked, written once by the briefing desk however the briefing ended:
  one column for each field of ``ports.BriefingRecord``. Nothing in it identifies the reader: no visitor code, no
  address, nothing from the request's headers.
- ``wts_configs``: the full settings behind each configuration id, stored once.
- ``wts_counts``: daily totals with no visitor code (how often a disclosure is opened, say), the same shape as
  Where MPs Stand's daily page-view totals.
- ``wts_weekly``: each week's totals for the site and for each configuration, kept indefinitely: they hold no
  question text.

How long a row is kept is the owner's decision (``OWNER_ACCEPTED``), applied by ``tidy``: a site's nightly update
calls it. The month arithmetic is the sites' own (Where Countries Stand's and Where Councils Stand's
``months_before``): the same day so many calendar months earlier, or the month's last day where that day does not
exist.
"""

from __future__ import annotations

import calendar
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, get_args

from wts_core.observe.config import canonical_json, config_id
from wts_core.ports import SYSTEM_CLOCK, BriefingConfig, BriefingLog, BriefingRecord, Clock, Outcome
from wts_core.state import Migration, StateDB, iso, today

__all__ = [
    "KINDS",
    "OUTCOMES",
    "OWNER_ACCEPTED",
    "Retention",
    "SqliteBriefingLog",
    "Tidied",
    "briefing_config",
    "count",
    "counts",
    "migrations",
    "months_before",
    "save_week",
    "weeks",
]

OUTCOMES: tuple[str, ...] = get_args(Outcome.__value__)
KINDS: tuple[str, ...] = ("reader", "check", "eval")

_FIELDS = tuple(f.name for f in fields(BriefingRecord))
_YES_OR_NO = ("follow_up", "reported", "corrected", "followed_up")


@dataclass(frozen=True)
class Retention:
    """How long the record is kept. Both numbers are the owner's to decide, so neither has a default."""

    months: int  # a whole row, in calendar months
    failed_question_days: int  # the question of a briefing that ended in an error


# The owner's decision of 13 November 2026 (ADR 0012): a row is kept for 13 months, long enough to compare a month
# with the same month a year before; the question of a briefing that could not be written is removed after 90
# days, which Where Countries Stand's privacy notice already promised and every site's now does.
OWNER_ACCEPTED = Retention(months=13, failed_question_days=90)


@dataclass(frozen=True)
class Tidied:
    """What a tidy removed: whole rows, and the questions of failed briefings."""

    deleted: int
    blanked: int


def months_before(when: datetime, months: int) -> datetime:
    """The same day ``months`` calendar months earlier (the month's last day where that day doesn't exist)."""
    y, m = divmod(when.month - 1 - months, 12)
    year, month = when.year + y, m + 1
    return when.replace(year=year, month=month, day=min(when.day, calendar.monthrange(year, month)[1]))


def migrations() -> tuple[Migration, ...]:
    """This module's tables, to pass to ``StateDB(path, migrations=…)`` with the other modules'."""
    return (
        Migration(40, "briefing_log", (
            "CREATE TABLE IF NOT EXISTS wts_briefing_log (id TEXT PRIMARY KEY, at TEXT NOT NULL, "
            "outcome TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'reader', "
            "question TEXT NOT NULL DEFAULT '', follow_up INTEGER NOT NULL DEFAULT 0, "
            "mode TEXT NOT NULL DEFAULT 'summary', filters_set TEXT NOT NULL DEFAULT '[]', "
            "config_id TEXT NOT NULL DEFAULT '', model TEXT, parse_model TEXT, instructions TEXT NOT NULL DEFAULT '', "
            "package_version TEXT NOT NULL DEFAULT '', site_version TEXT NOT NULL DEFAULT '', experiment TEXT, "
            "arm TEXT, sources INTEGER NOT NULL DEFAULT 0, spread TEXT, input_tokens INTEGER NOT NULL DEFAULT 0, "
            "cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0, "
            "cache_write_long_tokens INTEGER NOT NULL DEFAULT 0, "
            "output_tokens INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0, stop_reason TEXT, "
            "citations_total INTEGER, citations_invalid INTEGER, grounded_ratio REAL, unsupported INTEGER, "
            "quotes_unverified INTEGER, loaded_words INTEGER, t_parse INTEGER, t_search INTEGER, t_rank INTEGER, "
            "t_sources_sent INTEGER, t_first_token INTEGER, t_written INTEGER, t_checked INTEGER, t_total INTEGER, "
            "left_at TEXT, error_type TEXT, briefing_id TEXT, useful INTEGER, reported INTEGER NOT NULL DEFAULT 0, "
            "corrected INTEGER NOT NULL DEFAULT 0, followed_up INTEGER NOT NULL DEFAULT 0)",
            "CREATE INDEX IF NOT EXISTS wts_briefing_log_at ON wts_briefing_log (at)",
            "CREATE INDEX IF NOT EXISTS wts_briefing_log_briefing ON wts_briefing_log (briefing_id)",
        )),
        Migration(41, "configs", (
            "CREATE TABLE IF NOT EXISTS wts_configs (config_id TEXT PRIMARY KEY, first_seen TEXT NOT NULL, "
            "settings TEXT NOT NULL)",
        )),
        Migration(42, "counts", (
            "CREATE TABLE IF NOT EXISTS wts_counts (day TEXT NOT NULL, name TEXT NOT NULL, "
            "n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, name))",
        )),
        Migration(43, "weekly", (
            "CREATE TABLE IF NOT EXISTS wts_weekly (week TEXT NOT NULL, config_id TEXT NOT NULL DEFAULT '', "
            "written_at TEXT NOT NULL, figures TEXT NOT NULL, PRIMARY KEY (week, config_id))",
        )),
    )


def _at(when: datetime | str) -> str:
    """A time as the record stores it (ISO 8601, UTC, to the second), so that times compare as text."""
    moment = datetime.fromisoformat(when) if isinstance(when, str) else when
    if moment.tzinfo is None:
        raise ValueError(f"a time in the record of briefings must say its timezone: {when!r} does not")
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _stored(record: BriefingRecord) -> list[Any]:
    values: list[Any] = []
    for name in _FIELDS:
        value = getattr(record, name)
        if name == "at":
            value = _at(value)
        elif name == "filters_set":
            value = json.dumps(list(value))
        elif name == "spread":
            value = None if value is None else json.dumps(dict(value), sort_keys=True)
        elif name in _YES_OR_NO:
            value = int(bool(value))
        elif name == "useful":
            value = None if value is None else int(bool(value))
        values.append(value)
    return values


def _record(row: Mapping[str, Any]) -> BriefingRecord:
    values = {name: row[name] for name in _FIELDS}
    values["filters_set"] = tuple(json.loads(values["filters_set"] or "[]"))
    values["spread"] = None if values["spread"] is None else json.loads(values["spread"])
    for name in _YES_OR_NO:
        values[name] = bool(values[name])
    values["useful"] = None if values["useful"] is None else bool(values["useful"])
    return BriefingRecord(**values)


class SqliteBriefingLog:
    """The record of each briefing over ``wts_briefing_log`` (``ports.BriefingLog``), with the reading that the
    statistics need (``since``) and the nightly ``tidy``."""

    def __init__(self, db: StateDB, *, clock: Clock = SYSTEM_CLOCK) -> None:
        self._db = db
        self._clock = clock

    def write(self, record: BriefingRecord) -> None:
        """Store one briefing's record. It is written once: a second record with the same id is an error."""
        if record.outcome not in OUTCOMES:
            raise ValueError(f"a briefing cannot end as {record.outcome!r}: the outcomes are " + ", ".join(OUTCOMES))
        if record.kind not in KINDS:
            raise ValueError(f"a briefing cannot be of kind {record.kind!r}: the kinds are " + ", ".join(KINDS))
        marks = ", ".join("?" for _ in _FIELDS)
        with self._db.connect() as con:
            con.execute(f"INSERT INTO wts_briefing_log ({', '.join(_FIELDS)}) VALUES ({marks})", _stored(record))

    def mark(self, briefing_id: str, *, useful: bool | None = None, reported: bool = False, corrected: bool = False,
             followed_up: bool = False) -> None:
        """Note what a reader did after a briefing, on that briefing's record.

        A signal can only be added, never taken back: ``reported=False`` leaves an earlier report standing, and
        ``useful=None`` leaves an earlier answer; a later answer to "Was this useful?" replaces an earlier one.
        Where several rows name the same saved briefing (it was written once and then served again from the
        cache), the earliest is marked, the one that holds the briefing's own timings and checks: one signal is
        counted once. A briefing with no row (it was written before the record was switched on, or its row has
        been tidied away) is left alone.
        """
        if not briefing_id:
            return
        with self._db.connect() as con:
            con.execute(
                "UPDATE wts_briefing_log SET useful = coalesce(?, useful), reported = max(reported, ?), "
                "corrected = max(corrected, ?), followed_up = max(followed_up, ?) WHERE rowid = "
                "(SELECT rowid FROM wts_briefing_log WHERE briefing_id = ? ORDER BY at, rowid LIMIT 1)",
                (None if useful is None else int(useful), int(reported), int(corrected), int(followed_up),
                 briefing_id))

    def since(self, start: datetime | str, end: datetime | str | None = None,
              kinds: Sequence[str] = ("reader",)) -> list[BriefingRecord]:
        """The records from ``start`` up to but not including ``end`` (no end: all that follow), oldest first, of
        the kinds named: readers' questions only unless asked, so the nightly check's question and the evaluation
        harness's never colour the figures by accident."""
        sql = f"SELECT * FROM wts_briefing_log WHERE at >= ? AND kind IN ({', '.join('?' for _ in kinds)})"
        args: list[str] = [_at(start), *kinds]
        if end is not None:
            sql += " AND at < ?"
            args.append(_at(end))
        with self._db.connect() as con:
            return [_record(r) for r in con.execute(sql + " ORDER BY at, rowid", args)]

    def tidy(self, retention: Retention) -> Tidied:
        """Apply the retention: delete every row older than ``retention.months`` calendar months, and blank the
        question of every briefing that ended in an error more than ``retention.failed_question_days`` days ago.
        Pass ``OWNER_ACCEPTED`` unless the owner has decided otherwise."""
        now = self._clock.now()
        too_old = _at(months_before(now, retention.months))
        failed_too_old = _at(now - timedelta(days=retention.failed_question_days))
        with self._db.connect() as con:
            deleted = con.execute("DELETE FROM wts_briefing_log WHERE at < ?", (too_old,)).rowcount
            blanked = con.execute("UPDATE wts_briefing_log SET question = '' WHERE outcome = 'error' AND at < ? "
                                  "AND question != ''", (failed_too_old,)).rowcount
        return Tidied(deleted=deleted, blanked=blanked)

    # ---- the settings behind each configuration id -------------------------------------------------------------

    def remember_config(self, config_id: str, settings: Mapping[str, Any]) -> None:
        """Keep the full settings behind a configuration id, the first time it is seen. Never a key or a
        password: pass what ``config_id`` was made from."""
        with self._db.connect() as con:
            con.execute("INSERT OR IGNORE INTO wts_configs (config_id, first_seen, settings) VALUES (?, ?, ?)",
                        (config_id, iso(self._clock), canonical_json(settings)))

    def config(self, config_id: str) -> dict[str, Any] | None:
        """The settings stored for a configuration id, or None if it was never remembered."""
        with self._db.connect() as con:
            row = con.execute("SELECT settings FROM wts_configs WHERE config_id = ?", (config_id,)).fetchone()
        return None if row is None else dict(json.loads(row["settings"]))


if TYPE_CHECKING:  # checked by mypy: the class is what its interface asks for

    def _as_briefing_log(x: SqliteBriefingLog) -> BriefingLog:
        return x


# ---- the configuration a site's briefings run with ---------------------------------------------------------------

_NAMED = ("model", "parse_model", "instructions", "package_version", "site_version", "experiment", "arm")


def briefing_config(*, log: SqliteBriefingLog | None, model: str, parse_model: str | None, instructions: str,
                    site_version: str, experiment: str | None = None, arm: str | None = None,
                    also: Mapping[str, Any] | None = None) -> BriefingConfig:
    """The configuration a site's briefings run with (``ports.BriefingConfig``), made once when the site starts
    and given to the briefing desk: its id worked out, and the parts behind the id kept in ``wts_configs`` by the
    same call, so that a site cannot do one and forget the other.

    ``log`` is the site's record of briefings, or None, said out loud, on a site that has not turned the record
    on: the configuration is then made and nothing is kept. ``model`` writes the briefing and ``parse_model`` reads
    the question (None where the site's own rules read every one); ``instructions`` is the version of the site's
    instructions to the model; ``also`` is everything else that could change a briefing (the provider, the
    embedder, the retrieval settings). The package's own version is added here. An experiment and its arm are part
    of the id only while there is one.

    The id is ``config_id`` of all of that. Never pass a key, a password or anything about a reader: the parts are
    stored as they are."""
    from wts_core import __version__  # here, not at the top: this module is read while the package is

    more = dict(also or {})
    clash = sorted(set(more) & {"config_id", *_NAMED})
    if clash:
        raise ValueError("briefing_config: " + ", ".join(clash) + " is given by name, so it cannot be in `also` "
                         "as well")
    parts: dict[str, Any] = {"model": model, "parse_model": parse_model, "instructions": instructions,
                             "package_version": __version__, "site_version": site_version}
    if experiment is not None or arm is not None:
        parts.update(experiment=experiment, arm=arm)
    parts.update(more)
    made = config_id(parts)
    if log is not None:
        log.remember_config(made, parts)
    return BriefingConfig(config_id=made, model=model, parse_model=parse_model, instructions=instructions,
                          package_version=__version__, site_version=site_version, experiment=experiment, arm=arm,
                          settings=parts)


# ---- daily totals -----------------------------------------------------------------------------------------------


def count(db: StateDB, name: str, clock: Clock = SYSTEM_CLOCK, *, n: int = 1) -> None:
    """Add to today's total for ``name``. A total and nothing more: no visitor code, no time of day."""
    with db.connect() as con:
        con.execute("INSERT INTO wts_counts (day, name, n) VALUES (?, ?, ?) "
                    "ON CONFLICT(day, name) DO UPDATE SET n = n + excluded.n", (today(clock), name, n))


def counts(db: StateDB, since: date | str) -> dict[str, dict[str, int]]:
    """Each name's daily totals from the day ``since`` on: name, then day (``YYYY-MM-DD``), then the total."""
    day = since if isinstance(since, str) else since.isoformat()
    found: dict[str, dict[str, int]] = {}
    with db.connect() as con:
        for r in con.execute("SELECT day, name, n FROM wts_counts WHERE day >= ? ORDER BY name, day", (day[:10],)):
            found.setdefault(r["name"], {})[r["day"]] = int(r["n"])
    return found


# ---- weekly totals ----------------------------------------------------------------------------------------------


def save_week(db: StateDB, week: str, config_id: str, figures: Mapping[str, Any],
              clock: Clock = SYSTEM_CLOCK) -> None:
    """Keep a week's totals (``week`` as ``2026-W46``) for one configuration, or for the whole site under the
    configuration id ``""``. Writing a week again replaces it. ``figures`` must hold counts, rates and medians
    only, never a question: these rows are kept indefinitely."""
    with db.connect() as con:
        con.execute("INSERT INTO wts_weekly (week, config_id, written_at, figures) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(week, config_id) DO UPDATE SET written_at = excluded.written_at, "
                    "figures = excluded.figures", (week, config_id, iso(clock), canonical_json(figures)))


def weeks(db: StateDB, since: str = "") -> dict[str, dict[str, dict[str, Any]]]:
    """The weekly totals kept, from the week ``since`` on (``2026-W46``; none given: all): week, then
    configuration id (``""`` for the whole site), then the figures."""
    found: dict[str, dict[str, dict[str, Any]]] = {}
    with db.connect() as con:
        for r in con.execute("SELECT week, config_id, figures FROM wts_weekly WHERE week >= ? "
                             "ORDER BY week, config_id", (since,)):
            found.setdefault(r["week"], {})[r["config_id"]] = dict(json.loads(r["figures"]))
    return found
