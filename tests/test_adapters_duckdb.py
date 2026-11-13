"""The DuckDB connection shared between threads: Where MPs Stand's three tests of its ``store/shared.py``, on
DuckDB 2. (Where Countries Stand's copy of the file has the same three.)"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
from typing import Any

import pytest

from wts_core.adapters.duckdb import SharedConnection, shared

# the tests that open a database need the duckdb extra; the last one, that the adapter is imported without it, does not
needs_duckdb = pytest.mark.skipif(importlib.util.find_spec("duckdb") is None,
                                  reason="DuckDB is not installed: uv sync --extra duckdb")


def a_table(con: SharedConnection, x: int) -> Any:
    """Something to register: an Arrow table, as the sites register, where pyarrow is installed (it comes with the
    ``ai`` extra, not with ``duckdb``); otherwise a relation, which DuckDB keeps for the registering thread alone in
    the same way. Made on a cursor of its own, so that the shared connection's is left as it was."""
    try:
        import pyarrow as pa
    except ImportError:
        return con._base.cursor().sql(f"SELECT {x} AS x")
    return pa.table({"x": [x]})


@needs_duckdb
def test_threads_get_their_own_results():
    con = shared()
    con.execute("CREATE TABLE t AS SELECT range AS i FROM range(200000)")
    errors: list[str] = []

    def work(n: int) -> None:
        try:
            for _ in range(20):
                got = con.execute("SELECT sum(i) + ? FROM t", [n]).fetchone()[0]
                assert got == 19999900000 + n
        except Exception as exc:  # collected so the test can report it
            errors.append(repr(exc))

    threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


@needs_duckdb
def test_views_and_settings_are_shared_registrations_are_not():
    con = shared()
    con.execute("CREATE VIEW v AS SELECT 1 AS x")
    con.register("mine", a_table(con, 1))
    assert con.execute("SELECT x FROM mine").fetchall() == [(1,)]
    seen: dict[str, object] = {}

    def other() -> None:
        seen["view"] = con.execute("SELECT x FROM v").fetchone()[0]
        try:
            con.execute("SELECT * FROM mine").fetchall()
            seen["registered"] = True
        except Exception:
            seen["registered"] = False

    t = threading.Thread(target=other)
    t.start()
    t.join()
    assert seen == {"view": 1, "registered": False}
    assert shared(con) is con


@needs_duckdb
def test_a_row_read_singly_does_not_block_the_next_registration_or_relation():
    """DuckDB 2 refuses to register a table or run a relation while the cursor's last result has rows unread, which
    is how every fetchone() that finds its row leaves it. A request thread keeps its cursor, so one lookup would
    otherwise break the next search on that thread."""
    con = shared()
    con.execute("CREATE TABLE t AS SELECT range AS i FROM range(5000)")
    seven = a_table(con, 7)
    assert con.execute("SELECT i FROM t ORDER BY i").fetchone() == (0,)
    con.register("mine", seven)
    assert con.execute("SELECT x FROM mine").fetchone() == (7,)
    assert con.sql("SELECT count(*) FROM t").fetchall() == [(5000,)]
    assert con.execute("SELECT i FROM t ORDER BY i").fetchone() == (0,)
    assert con.table("t").limit(1).fetchall() == [(0,)]


@needs_duckdb
def test_a_connection_that_is_given_is_wrapped_and_each_thread_has_one_cursor_on_it():
    import duckdb

    base = duckdb.connect()
    base.execute("CREATE TABLE t AS SELECT 42 AS x")
    con = shared(base)
    assert con.execute("SELECT x FROM t").fetchone() == (42,)
    assert con.cursor_for_thread() is con.cursor_for_thread()
    theirs: list[Any] = []
    t = threading.Thread(target=lambda: theirs.append(con.cursor_for_thread()))
    t.start()
    t.join()
    assert theirs[0] is not con.cursor_for_thread()


def test_the_adapter_is_imported_without_duckdb():
    """DuckDB is asked for when the first connection is opened: a site that does not use it needn't install it."""
    code = ("import sys; sys.modules['duckdb'] = None\n"  # as if it were not installed
            "from wts_core.adapters.duckdb import SharedConnection, shared\n"
            "try:\n    shared()\nexcept ImportError:\n    print('asked for when first used')\n")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.stdout == "asked for when first used\n", done.stderr
