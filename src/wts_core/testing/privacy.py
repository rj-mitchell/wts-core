"""Three promises every site makes, as checks a site's own tests call with its real pipeline.

``assert_no_reader_data``: after a question has been asked, nothing the package keeps or logs holds the reader's
address; the visitor's code is nowhere but the two places it is counted; and the question itself is only where the
sites' privacy notices say a question is kept (ADR 0012).

``assert_statements_stay_out``: a statement under the right of reply never reaches the model, the search index or
the record (ADR 0008). It publishes a statement that carries a marker found nowhere else, asks a question through
the site's own pipeline with the recording fakes of ``wts_core.testing``, and fails if the marker turns up anywhere
but the right of reply's own tables.

``assert_briefings_tied_to_no_one``: once its day is over, no row of the record of briefings can be tied to a
visitor or to a signed-in account through what the record and the spending rows share: their times and their token
counts (ADR 0012, "What is kept about spending, and what can be promised").

The first two read every row of every ``wts_`` table in the state database. A site's own tables are its own to
check.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol

from wts_core.ports import SYSTEM_CLOCK, SYSTEM_RANDOM, Clock, Random
from wts_core.replies import Replies
from wts_core.replies import migrations as replies_migrations
from wts_core.state import StateDB

__all__ = ["EmbedderSeen", "IndexSeen", "ModelSeen", "assert_briefings_tied_to_no_one", "assert_no_reader_data",
           "assert_statements_stay_out", "split_by_account_totals"]


# The four things ``assert_statements_stay_out`` reads of the site's model, embedder and index. The package's own
# stand-ins have them (``ScriptedModel``, ``RecordingEmbedder``, ``MemoryIndex``); so does anything of a site's own
# that can say the same of the real thing it wraps: its real model client over a faked SDK, its real index.


class ModelSeen(Protocol):
    """What a model was asked: every request for a briefing, and every question it was asked to read."""

    @property
    def requests(self) -> Sequence[Any]: ...

    @property
    def structured_requests(self) -> Sequence[Any]: ...


class EmbedderSeen(Protocol):
    """Every text an embedder was given, documents and questions alike."""

    @property
    def texts(self) -> Sequence[str]: ...


class IndexSeen(Protocol):
    """What an index holds: every row in it now and, where it can say, every row ever written to it.
    ``adapters.lancedb.LanceIndex`` has this, so a site's real index is passed as it is."""

    def everything(self) -> Iterable[Any]: ...

# Where a reader's question may be kept (ADR 0012, "Retention"; ``usage/tables.py``): with
# the saved briefing, in the replay kept for answering the same question again, in the briefing record, and in the
# note of a briefing that failed.
_QUESTION_KEPT_IN: Mapping[str, tuple[str, ...]] = {
    "wts_briefings": ("question", "events"),
    "wts_answer_cache": ("events",),
    "wts_briefing_log": ("question",),
    "wts_failures": ("question",),
}
# Where the day's visitor code may be kept: the spending record, for the daily limit, and the day's count of
# reports and statements sent, which is emptied each day.
_VISITOR_KEPT_IN: Mapping[str, tuple[str, ...]] = {
    "wts_spending": ("visitor",),
    "wts_reply_counts": ("visitor",),
}


def assert_no_reader_data(state: StateDB, log_lines: Iterable[str], *, address: str, question: str | None = None,
                          visitor: str | None = None) -> None:
    """Fail if anything about the reader who asked ``question`` from ``address`` is kept where it should not be.

    Call it after the question has been asked through the site's pipeline, with the lines its logging wrote. A
    site with no questions (Where Landlords Stand, where readers search and no briefing is written) leaves
    ``question`` out and calls it after a reader's request of whatever kind: the address and the visitor's code
    are checked just the same.

    * ``address`` (the reader's network address, as the request carried it) must be in no ``wts_`` table and no
      log line.
    * ``visitor`` (the day's visitor code for that address, if the site gives it) must be in no log line, and in no
      ``wts_`` table but ``wts_spending.visitor`` and ``wts_reply_counts.visitor``.
    * ``question`` must be in no log line, and in no ``wts_`` table but these, which are where the sites' privacy
      notices say a question is kept: ``wts_briefings.question`` and ``wts_briefings.events`` (the saved briefing),
      ``wts_answer_cache.events`` (the replay for the same question asked again), ``wts_briefing_log.question``
      (the record of each briefing) and ``wts_failures.question`` (the note of a briefing that failed).

    Give a question and an address that could be nothing else: a search for "a" proves nothing."""
    wanted = {**({"question": (question, _QUESTION_KEPT_IN)} if question is not None else {}),
              "address": (address, {}), **({"visitor": (visitor, _VISITOR_KEPT_IN)} if visitor else {})}
    for what, (needle, _) in wanted.items():
        if len((needle or "").strip()) < 6:
            raise ValueError(f"the {what} to look for is too short to prove anything: {needle!r}")
    lines = list(log_lines)
    found: list[str] = []
    for what, (needle, allowed) in wanted.items():
        found += [f"the {what} is in {table}.{column}" for table, column in _kept_in(state, needle)
                  if column not in allowed.get(table, ())]
        found += [f"the {what} is in a log line: {line.strip()[:200]}" for line in lines if _holds(line, needle)]
    if found:
        raise AssertionError("something about a reader is kept where it should not be:\n  " + "\n  ".join(found))


def assert_statements_stay_out(*, replies: Replies, ask: Callable[[str], Iterable[Any]], model: ModelSeen,
                               embedder: EmbedderSeen, index: IndexSeen, state: StateDB,
                               log_lines: Callable[[], Iterable[str]] | Iterable[str], item: str, question: str,
                               about: str | None = None, random: Random = SYSTEM_RANDOM) -> None:
    """Fail if a published statement reaches the model, the embedder, the search index, the record or a log.

    The site builds its real pipeline over what it passes here, with ``state`` as its state database and
    ``replies`` its ``Replies``. ``model``, ``embedder`` and ``index`` are the package's stand-ins
    (``ScriptedModel``, ``RecordingEmbedder``, ``MemoryIndex``) or anything of the site's own that can say what
    they say (``ModelSeen``, ``EmbedderSeen``, ``IndexSeen``): its real index, its real model client over a faked
    SDK. A look-alike index with ``rows``, ``vector_rows`` and ``added`` and no ``everything`` is also read.
    Then ``ask`` asks a question through that pipeline and gives the events a reader would be sent. ``item`` is
    the address of something a statement can sit beside, and ``question`` a question about it, so that the
    pipeline has every reason to meet the statement; ``about`` is whom the statement speaks for, where the site
    must be told (Where Landlords Stand, for an area's page).

    A statement is sent and published whose name, role, words, link and confirming address all carry one marker
    that is nowhere else. Then the question is asked, and the marker must not be in: any request the model was
    given; anything given to the embedder; anything in, or ever written to, the index; any event the reader was
    sent; any ``wts_`` table but the right of reply's own (``wts_statements``, ``wts_statement_log`` and the
    others its migrations make); or any log line. ``log_lines`` is the lines the site's logging wrote, or
    something that returns them, read after the question has been asked.

    It also fails if the statement was not shown, or the question never reached the model: a check that passes
    because nothing happened proves nothing."""
    marker = "wtsmarker" + random.token_hex(6).lower()
    sid = replies.submit(
        name=f"Marker {marker}", role=f"Spokesperson for {marker}", item=item, link=f"https://example.org/{marker}",
        text=f"This statement is here to be found nowhere else: {marker}. It must never reach the model, the search "
             "index or the record.", email=f"{marker}@example.org")
    if sid is None:
        raise AssertionError("the statement was not taken: nothing was kept")
    replies.publish(sid, checked="Confirmed for the test that statements stay out.", about=about)
    if not any(shown["id"] == sid for shown in replies.published(everywhere=True)):
        raise AssertionError(f"the statement was published but is not shown (is {item} hidden?): nothing to keep out")

    events = list(ask(question))
    if not model.requests and not model.structured_requests:
        raise AssertionError("the question never reached the model, so this proves nothing: ask one the site "
                             "finds sources for, with nothing in the answer cache")
    lines = list(log_lines() if callable(log_lines) else log_lines)

    own = _tables_of_replies()
    found = [f"a request to the model ({n + 1} of {len(model.requests)})"
             for n, request in enumerate(model.requests) if _holds(repr(request), marker)]
    found += ["a question the model was asked to read" for request, _ in model.structured_requests
              if _holds(repr(request), marker)]
    found += ["a text given to the embedder" for text in embedder.texts if _holds(text, marker)]
    everything = getattr(index, "everything", None)
    held = ([("a row in it, or written to it", list(everything()))] if everything is not None else
            # an index look-alike written for 0.2.1, which was read by these three names
            [(where, getattr(index, name)) for where, name in (("its rows", "rows"), ("its vectors' rows",
                                                                                      "vector_rows"),
                                                               ("a row written to it", "added"))])
    found += [f"the index ({where})" for where, rows in held if _holds(repr(rows), marker)]
    found += ["an event sent to the reader" for event in events if _holds(repr(event), marker)]
    found += [f"{table}.{column}" for table, column in _kept_in(state, marker) if table not in own]
    found += [f"a log line: {line.strip()[:200]}" for line in lines if _holds(line, marker)]
    if found:
        raise AssertionError("a statement under the right of reply reached where it must never be:\n  "
                             + "\n  ".join(dict.fromkeys(found)))


# columns that would say who a row was for, wherever they were: none may sit beside a second a record can be given
_WHO = frozenset({"visitor", "account", "user", "user_id", "address", "ip", "email"})


def assert_briefings_tied_to_no_one(state: StateDB, *, clock: Clock = SYSTEM_CLOCK) -> None:
    """Fail if a row of the record of briefings can be tied to a visitor or a signed-in account once its day is
    over, by anything the package keeps.

    The record holds no visitor's code and no account. But it shares its token counts and its cost with the
    spending rows, which for a day say who each call was for, and to the second when. So this goes about it as
    someone holding the database would, on everything from before today (by ``clock``, in UTC), and fails on
    each of these:

    * a record's time finer than the hour, or a spending row's finer than its day: matched by their
      token counts, the row would give the record its second back, and a spending row is the one thing that
      for a day says who;
    * a visitor's code or an account kept beside a second anywhere else a record can be matched to: the
      answer cache, the notes of failed briefings and the saved briefings each keep the second something was
      stored (below), and must hold nothing that says who;
    * a spending row that still holds a visitor's code, or says it was a signed-in account's at all. "Some
      account" is a mark too: with it the day's rows fall into the accounts' and the public's, and the accounts'
      can then be dealt out among the few accounts there are;
    * anything kept about an account more finely than the calendar month and the cent: a total by the day,
      a month's cost with more than two decimal places, a day's count of the visitors an account was seen with;
    * the attack itself (``split_by_account_totals``): every way of making up each account's kept total out
      of the records of its month is tried, and a record is "given to" an account when it is in every one.
      Any record given to an account fails the check.

    Call it after the site has been used across midnight and the day before has been forgotten (the nightly
    tidy, or the new day's first model call). Give it a database in which an account was not alone: if the
    only briefings of a month were one account's, its month's total is made up of them and nothing else, the
    attack succeeds, and that is true of the real site too (below). Two briefings of like cost, one signed in
    and one not, are enough for a test.

    What is promised, then: once its day is over, a record of a briefing is beside nothing that says whose
    it was. The spending rows of that day say "somebody" at most, alike for an account and for the public; they
    keep the day and no time, so no time finer than its hour can be given back to a record from the spending
    rows; and for each account there is one line a calendar month: its calls, its cost to the cent, and how
    many visitors' codes it was seen with.

    What is not promised, because it is not so:

    * *Today's rows.* While its day lasts a spending row holds the visitor's code, the account and the second,
      for the daily limits, and a record of today can be matched to it.
    * *A month in which an account's briefings were the only ones, or nearly.* Its total is then the sum of
      those records and of no other set, and they are its own. The same holds on the first days of a month,
      when the month so far is a day or two.
    * *A site on which everyone signs in.* With no public to be lost among, every record of a day is some
      account's, and the totals deal a part of them out (docs/adr/0012 has the measured numbers).
    * *A briefing that cost unlike any other.* An account that asked once in a month, at a cost no other
      briefing of the month comes within half a cent of, is given that briefing by its total alone.
    * *Two copies of the database from different nights* (two backups): the difference between an account's
      month in each is what it spent between them, to the cent, and its calls exactly. docs/adr/0012 has what
      this attack was measured to give back, with one copy and with a copy of every night.
    * *A record's second, from elsewhere than the spending rows.* Three of the package's tables keep the second
      something was stored, and a record can be matched to each by its question or its briefing: the answer
      cache (``wts_answer_cache.created_at``), for as long as the site keeps a cached answer (a week on every
      site: the time decides when a cached answer stops being served, so it is not coarsened); the note of a
      briefing that failed (``wts_failures.at``), for 90 days; and the saved briefing
      (``wts_briefings.created_at``), for good, as each site's own table always kept it. So a record that was
      written, replayed, found no records or failed can be given its second for those times. Each of the three
      is tied to no one: none holds a visitor's code, an account or an address, which is asserted here.
    * *The structured log*, for the 14 days it is kept: its lines hold each record's id beside the second the
      line was written, and nothing about who asked."""
    day = clock.now().strftime("%Y-%m-%d")
    found: list[str] = []
    with state.connect() as con:
        tables = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "wts_briefing_log" not in tables:
            raise AssertionError("this state database has no record of briefings (wts_briefing_log): nothing to check")
        fine = con.execute("SELECT count(*), min(at) FROM wts_briefing_log WHERE substr(at, 14, 6) != ':00:00'"
                           ).fetchone()
        if fine[0]:
            found.append(f"{fine[0]} rows of wts_briefing_log keep their time finer than the hour (such as "
                         f"{fine[1]})")
        if "wts_spending" in tables:
            before = "FROM wts_spending WHERE at < ?"
            coded = con.execute(f"SELECT count(*) {before} AND visitor IS NOT NULL AND visitor != ''",
                                (day,)).fetchone()[0]
            if coded:
                found.append(f"{coded} rows of wts_spending from before {day} still hold a visitor's code")
            marked = con.execute(f"SELECT count(*), group_concat(DISTINCT account) {before} AND account IS NOT NULL",
                                 (day,)).fetchone()
            if marked[0]:
                found.append(f"{marked[0]} rows of wts_spending from before {day} still say they were a signed-in "
                             f"account's (account: {marked[1]})")
            timed = con.execute(f"SELECT count(*), min(at) {before} AND at != substr(at, 1, 10) || 'T00:00:00+00:00'",
                                (day,)).fetchone()
            if timed[0]:
                found.append(f"{timed[0]} rows of wts_spending from before {day} keep their time finer than the "
                             f"day (such as {timed[1]})")
                seconds = _seconds_given_back(con, day)
                if seconds:
                    found.append(f"{seconds} rows of wts_briefing_log from before {day} are given a second by the "
                                 "spending rows whose token counts add up to theirs")
        # where else a record can be given a second: each of these must say nothing of who
        for table in ("wts_answer_cache", "wts_failures", "wts_briefings"):
            whose = sorted({r["name"] for r in con.execute(f"PRAGMA table_info({table})")} & _WHO) \
                if table in tables else []
            if whose:
                found.append(f"{table} keeps the second a row was stored and has a column that says who "
                             f"({', '.join(whose)}): a record matched to it by its question would be given both")
        if "wts_account_days" in tables:
            found.append("wts_account_days keeps each account's total by the day")
        if "wts_visitor_days" in tables:
            daily = con.execute("SELECT count(*) FROM wts_visitor_days WHERE who != '*' AND length(day) > 7"
                                ).fetchone()[0]
            if daily:
                found.append(f"{daily} rows of wts_visitor_days count an account's visitors, or the public's apart "
                             "from the accounts', by the day")
        if "wts_account_months" in tables:
            finer = con.execute("SELECT count(*) FROM wts_account_months WHERE length(month) != 7 "
                                "OR abs(cost_usd * 100 - round(cost_usd * 100)) > 0.000001").fetchone()[0]
            if finer:
                found.append(f"{finer} rows of wts_account_months are kept more finely than the month and the cent")
    given = split_by_account_totals(state, clock=clock)
    if given:
        some = ", ".join(f"{record} to account {account}" for record, account in sorted(given.items())[:5])
        found.append(
            f"{len(given)} rows of wts_briefing_log from before {day} are given to one signed-in account by the "
            f"totals kept for it ({some}): each is in every way of making up the account's total out of the "
            "records of its time. Either a total is kept too finely, or in this database the account's briefings "
            "are the only ones that could make up its month: a test should have another asker's beside them")
    if found:
        raise AssertionError("a briefing's record can be tied to who asked:\n  " + "\n  ".join(found))


def split_by_account_totals(state: StateDB, *, clock: Clock = SYSTEM_CLOCK, tries: int = 300_000,
                            unsettled: list[tuple[str, int]] | None = None) -> dict[str, int]:
    """The records of briefings from before today that the totals kept for the signed-in accounts give to one
    account, each with that account: the attack an independent review made on 0.3.0 before it was released, on
    whatever the database keeps now. Empty where it gets nothing.

    For each total kept for an account (its calls and cost for a calendar month; or for a day, in a database
    that keeps such a thing), the records of that month or day that cost anything are gone through for every set
    of them whose costs add up to the total, within what the total's rounding allows, and whose model calls
    number the account's. How many calls a record took is read from the spending rows whose token counts add up
    to its own (one, two or three in a row); and if rows of days gone by say they were an account's, only the
    records of such rows are gone through, as the review did. A record that is in every set that fits is
    that account's, whichever way its total is made up: not only when one set fits (the second review found
    more than twice as many that way on a quiet site). A record that two accounts' totals both claim is left
    out.

    Nothing here is told who asked what: it reads only what anyone holding the file could. ``tries`` bounds the
    going through of every set for one total; past it, sets are made by chance until they have nothing in
    common. A total that is still not settled gives nothing, and is named in ``unsettled`` (a list, if one is
    given: the month or day, and the account), so that a measurement can say how many there were."""
    day = clock.now().strftime("%Y-%m-%d")
    with state.connect() as con:
        tables = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "wts_briefing_log" not in tables:
            return {}
        records = [(str(r[0]), str(r[1])[:10], float(r[2]), (int(r[3]), int(r[4]), int(r[5]))) for r in con.execute(
            "SELECT id, at, cost_usd, input_tokens, output_tokens, cache_read_tokens FROM wts_briefing_log "
            "WHERE at < ? AND cost_usd > 0 ORDER BY at, id", (day,))]
        kept: list[tuple[str, int, float, int, bool]] = []  # the time, the account, its cost and calls; rounded?
        if "wts_account_months" in tables:
            kept += [(str(r[0]), int(r[1]), float(r[2]), int(r[3]), True) for r in con.execute(
                "SELECT month, account, cost_usd, calls FROM wts_account_months WHERE calls > 0")]
        if "wts_account_days" in tables:  # an earlier design's, never released: tried so that it would be caught
            kept += [(str(r[0]), int(r[1]), float(r[2]), int(r[3]), False) for r in con.execute(
                "SELECT day, account, cost_usd, calls FROM wts_account_days WHERE calls > 0")]
        rows = _calls_of(con, day) if kept and "wts_spending" in tables else {}
    # First, which records could be an account's at all. A record whose spending rows are the site's own work is
    # nobody's. And where rows of days gone by are marked as an account's (they should not be), only the records
    # of such rows are an account's: the review's first step, which found the accounts' records exactly.
    marked = any(whose == "account" for _, whose in rows.values())
    said = [(rid, on, spent, rows.get((on, counts))) for rid, on, spent, counts in records]
    could_be: list[tuple[str, str, float, int | None]] = [
        (rid, on, spent, found[0] if found else None) for rid, on, spent, found in said
        if (found is not None and found[1] == "account") or (not marked and (found is None or found[1] != "site"))]
    claimed: dict[str, set[int]] = {}
    for when, account, cost, made, rounded in kept:
        among = [(rid, spent, took) for rid, on, spent, took in could_be if on.startswith(when)]
        # a month's total was rounded to the cent each night it was added to: half a cent for each day it may hold
        slack = 0.005 * max(1, len({on for _, on, _, _ in could_be if on.startswith(when)})) if rounded else 0.0
        its = _in_every_way(among, cost, made, slack + 0.000001, tries)
        if its is None and unsettled is not None:
            unsettled.append((when, account))
        for rid in its or ():
            claimed.setdefault(rid, set()).add(account)
    return {rid: next(iter(accounts)) for rid, accounts in claimed.items() if len(accounts) == 1}


def _runs(con: Any, day: str) -> Iterable[tuple[str, tuple[int, int, int], int, str, str]]:
    """Every one, two or three spending rows in a row, of one day before ``day``: the day, their token counts
    added up, how many rows, the last one's time, and what the rows say of whose they were: "account" where each
    says it was a signed-in account's, "site" where none was anybody's, and otherwise "somebody"."""
    rows = con.execute("SELECT at, input_tokens, output_tokens, cache_read_tokens, account, visitor FROM wts_spending "
                       "WHERE at < ? ORDER BY id", (day,)).fetchall()
    for first in range(len(rows)):
        total = [0, 0, 0]
        for last in range(first, min(first + 3, len(rows))):
            if str(rows[last][0])[:10] != str(rows[first][0])[:10]:
                break
            total = [total[n] + int(rows[last][n + 1]) for n in range(3)]
            run = rows[first:last + 1]
            whose = ("account" if all(r[4] is not None for r in run)
                     else "site" if all(r[4] is None and r[5] is None for r in run) else "somebody")
            yield str(rows[first][0])[:10], (total[0], total[1], total[2]), last - first + 1, str(rows[last][0]), whose


def _calls_of(con: Any, day: str) -> dict[tuple[str, tuple[int, int, int]], tuple[int, str]]:
    """For a record with these token counts, on this day: how many model calls it took, and whose its spending
    rows say they were (``_runs``), where the rows say one thing only."""
    said: dict[tuple[str, tuple[int, int, int]], set[tuple[int, str]]] = {}
    for on, counts, length, _, whose in _runs(con, day):
        said.setdefault((on, counts), set()).add((length, whose))
    return {key: next(iter(found)) for key, found in said.items() if len(found) == 1}


def _seconds_given_back(con: Any, day: str) -> int:
    """How many records from before ``day`` are given one time finer than their hour by the spending rows whose
    token counts add up to theirs."""
    times: dict[tuple[str, tuple[int, int, int]], set[str]] = {}
    for on, counts, _, at, _ in _runs(con, day):
        times.setdefault((on, counts), set()).add(at)
    given = 0
    for at, *counts in con.execute("SELECT at, input_tokens, output_tokens, cache_read_tokens FROM wts_briefing_log "
                                   "WHERE at < ? AND output_tokens > 0", (day,)):
        found = times.get((str(at)[:10], (int(counts[0]), int(counts[1]), int(counts[2]))), set())
        given += len(found) == 1 and not next(iter(found)).endswith("T00:00:00+00:00")
    return given


def _in_every_way(among: Sequence[tuple[str, float, int | None]], cost: float, calls: int, slack: float,
                  tries: int) -> tuple[str, ...] | None:
    """The records that are in EVERY set of these (each an id, a cost, and its model calls where known) whose
    costs add up to ``cost`` within ``slack`` and whose calls number ``calls``: those are the account's whichever
    way its total is made up. Empty when there is no such record (no set fits, or the sets that fit have nothing
    in common); None when that could not be settled within ``tries``.

    Every fitting set is gone through, the dearest records first, keeping what they all have in common, and
    the search ends as soon as they have nothing in common. Where there are so many records that the sets
    cannot all be gone through, sets are made another way (drawn at random and mended by exchanging one record
    for another until the costs fit): each one found still narrows what all have in common, and once that is
    nothing the answer is settled. Only a search that ends with something in common, and unfinished, is not."""
    items = sorted(among, key=lambda item: -item[1])  # the dearest first
    counted = all(made is not None for _, _, made in items)
    upto = [0.0]  # upto[n]: what the first n cost together
    for _, spent, _ in items:
        upto.append(upto[-1] + spent)
    to_come = [0] * (len(items) + 1)  # to_come[n]: the calls of every record from the nth on
    for n in range(len(items) - 1, -1, -1):
        to_come[n] = to_come[n + 1] + (items[n][2] or 1)
    common: set[str] | None = None  # what every set found so far has in it
    left = tries
    waiting: list[tuple[int, float, int, tuple[str, ...]]] = [(0, 0.0, 0, ())]  # a place, and what is chosen so far
    while waiting and left > 0 and (common is None or common):
        left -= 1
        place, spent, made, chosen = waiting.pop()
        room = calls - made  # at most this many more records: each took one call at least
        if place >= len(items) or room <= 0 or spent > cost + slack:
            continue
        if spent + upto[min(place + room, len(items))] - upto[place] < cost - slack:
            continue  # even the dearest that could still be added would not reach it
        if counted and to_come[place] < room:
            continue  # nor are there calls enough left among the records still to come
        rid, its_cost, its_calls = items[place]
        took = its_calls or 1
        waiting.append((place + 1, spent, made, chosen))  # without this record
        if took <= room:
            with_it, so_far = (*chosen, rid), spent + its_cost
            if abs(so_far - cost) <= slack and (made + took == calls or not counted):
                common = set(with_it) if common is None else common & set(with_it)
            waiting.append((place + 1, so_far, made + took, with_it))
    if common is not None and not common:
        return ()  # two sets that fit have nothing in common: no record is in every one
    if not waiting:
        return tuple(sorted(common or ()))  # every set has been gone through
    # not all gone through: more sets, made by chance and mended, until they have nothing in common
    for found in _sets_by_chance(items, cost, calls, slack, counted, attempts=60):
        common = found if common is None else common & found
        if not common:
            return ()
    return None


def _sets_by_chance(items: Sequence[tuple[str, float, int | None]], cost: float, calls: int, slack: float,
                    counted: bool, attempts: int) -> Iterable[set[str]]:
    """Sets of records whose calls number ``calls`` and whose costs fit, each made by drawing records at random
    and then exchanging one in the set for one outside it, of the same number of calls, while that brings the
    costs nearer. The same sets each time it is asked: the chance is seeded."""
    import random

    rng = random.Random(len(items) * 1_000_003 + calls)
    for _ in range(attempts):
        order = list(range(len(items)))
        rng.shuffle(order)
        inside: list[int] = []
        room = calls
        for n in order:
            took = items[n][2] or 1
            if took <= room:
                inside.append(n)
                room -= took
            if room == 0:
                break
        if room and counted:
            continue
        outside = [n for n in order if n not in set(inside)]
        total = sum(items[n][1] for n in inside)
        for _ in range(4000):
            if abs(total - cost) <= slack or not outside:
                break
            a, b = rng.randrange(len(inside)), rng.randrange(len(outside))
            if (items[inside[a]][2] or 1) != (items[outside[b]][2] or 1):
                continue
            changed = total - items[inside[a]][1] + items[outside[b]][1]
            if abs(changed - cost) < abs(total - cost):
                inside[a], outside[b] = outside[b], inside[a]
                total = changed
        if abs(total - cost) <= slack:
            yield {items[n][0] for n in inside}


def _tables_of_replies() -> set[str]:
    made = re.compile(r"CREATE TABLE IF NOT EXISTS (wts_\w+)")
    return {m.group(1) for migration in replies_migrations() for statement in migration.statements
            for m in [made.match(statement)] if m}


def _holds(text: str, needle: str) -> bool:
    """Whether ``needle`` is in ``text``, as it is or as JSON writes it (quotes and letters outside ASCII escaped),
    whatever its case."""
    lowered = text.lower()
    forms = {needle, json.dumps(needle)[1:-1], json.dumps(needle, ensure_ascii=False)[1:-1]}
    return any(form.lower() in lowered for form in forms)


def _kept_in(state: StateDB, needle: str) -> list[tuple[str, str]]:
    """Every column of every ``wts_`` table that holds ``needle`` in some row."""
    found: dict[tuple[str, str], None] = {}
    with state.connect() as con:
        for table in sorted(t for t in state.tables() if t.startswith("wts_")):
            for row in con.execute(f"SELECT * FROM {table}"):
                for column in row.keys():  # noqa: SIM118 (a sqlite3.Row is not a mapping to iterate)
                    value = row[column]
                    if value is not None and _holds(value.decode("utf-8", "replace") if isinstance(value, bytes)
                                                    else str(value), needle):
                        found[(table, column)] = None
    return list(found)
