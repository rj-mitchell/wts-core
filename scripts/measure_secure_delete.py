"""What overwriting deleted content costs: the figures summarised in docs/adr/0005, and how to take them again.

``StateDB`` asks SQLite to overwrite what it deletes (``PRAGMA secure_delete = ON``) on every connection. This
times the write-heavy paths of a site with it on and off, on a database with a rollback journal (three sites) and
on one with a write-ahead log (Where MPs Stand):

* the spending record: one row for each model call, each in its own connection, as a site writes them;
* forgetting a day's visitor codes: one update over every row of the day;
* the answer cache: storing answers (each replaces the one before under its key) and the nightly purge;
* writing the file out afresh (``StateDB.compact``).

Run it with ``uv run python scripts/measure_secure_delete.py [rows]``. It writes only under a temporary folder.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from wts_core import usage
from wts_core.ports import Usage
from wts_core.state import StateDB
from wts_core.testing import FixedClock
from wts_core.usage import PriceTable, Spending, SqliteAnswerCache

PRICES = PriceTable.from_settings({"price_input_per_mtok": 3.0, "price_output_per_mtok": 15.0,
                                   "price_cache_read_per_mtok": 0.3, "cache_write_multiplier": 1.25})
ANSWER = [{"type": "text", "text": "A briefing of some length, as the cache keeps it. " * 120}]


def _plain(self: StateDB, *, alone: bool = False) -> sqlite3.Connection:
    """A connection with secure_delete off: nothing asked of SQLite about what it deletes."""
    con = sqlite3.connect(self.path, timeout=30, isolation_level=None) if alone \
        else sqlite3.connect(self.path, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def measure(folder: Path, *, secure: bool, wal: bool, rows: int) -> dict[str, float]:
    path = folder / f"state-{'secure' if secure else 'plain'}-{'wal' if wal else 'journal'}.db"
    if wal:
        sqlite3.connect(path).execute("PRAGMA journal_mode = WAL").close()
    clock = FixedClock("2026-11-13T09:00:00+00:00")
    db = StateDB(path, migrations=usage.migrations(), clock=clock)
    spending, cache = Spending(db, PRICES, clock=clock), SqliteAnswerCache(db, clock=clock)
    took: dict[str, float] = {}

    def timed(name: str, start: float) -> None:
        took[name] = (time.perf_counter() - start) * 1000

    start = time.perf_counter()
    for n in range(rows):
        spending.add("answer", "a-model", Usage(input_uncached=9000, output=700), visitor=f"visitor{n % 50:04d}")
    timed("spending: a row", start)
    took["spending: a row"] /= rows
    clock.advance(days=1)
    start = time.perf_counter()
    spending.forget_visitors()
    timed(f"forgetting the codes on {rows} rows", start)
    start = time.perf_counter()
    for n in range(rows // 10):
        cache.put(f"key{n % 20}", ANSWER, 168)
    timed("the cache: an answer stored", start)
    took["the cache: an answer stored"] /= rows // 10
    clock.advance(days=8)
    start = time.perf_counter()
    cache.purge(168)
    timed("the cache: the nightly purge of 20 answers", start)
    start = time.perf_counter()
    db.compact()
    timed("writing the file out afresh", start)
    took["the file, in KiB"] = path.stat().st_size / 1024
    return took


def main() -> None:
    rows = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    their_own = StateDB._open
    with tempfile.TemporaryDirectory() as tmp:
        for wal in (False, True):
            found = {}
            for secure in (False, True):
                StateDB._open = their_own if secure else _plain  # type: ignore[method-assign]
                best: dict[str, float] = {}
                for attempt in range(3):  # the best of three: a disk is a noisy thing to time
                    folder = Path(tmp) / f"{wal}-{secure}-{attempt}"
                    folder.mkdir()
                    for name, ms in measure(folder, secure=secure, wal=wal, rows=rows).items():
                        best[name] = min(best.get(name, ms), ms)
                found[secure] = best
            StateDB._open = their_own  # type: ignore[method-assign]
            print(f"\n{'A write-ahead log' if wal else 'A rollback journal'} ({rows} spending rows), in "
                  "milliseconds: off, on, and the difference")
            for name in found[True]:
                off, on = found[False][name], found[True][name]
                print(f"  {name:45s} {off:9.3f} {on:9.3f}  {(on - off) / off * 100 if off else 0:+6.1f}%")


if __name__ == "__main__":
    main()
