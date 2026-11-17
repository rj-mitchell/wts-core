"""The two checks a site's own tests call: nothing about a reader is kept where it should not be, and statements
under the right of reply stay out of the model, the index, the record and the logs. Each is shown to pass on a
small site that keeps the promises, and to fail on one that breaks them, one way at a time."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from test_replies_sites import BARNSLEY, SITES
from wts_core import observe, usage
from wts_core import replies as right_of_reply
from wts_core.events import TextDelta
from wts_core.ports import BriefingRecord, Document, ModelRequest, Usage
from wts_core.replies import Replies
from wts_core.state import StateDB
from wts_core.testing import (
    FixedClock,
    FixedRandom,
    assert_briefings_tied_to_no_one,
    assert_no_reader_data,
    assert_statements_stay_out,
    split_by_account_totals,
)
from wts_core.testing.index import MemoryIndex, RecordingEmbedder
from wts_core.testing.models import ScriptedModel, recorded

QUESTION = "What has Barnsley council decided about weekly bin collections?"
ADDRESS = "203.0.113.77"
ITEM = f"/councils/{BARNSLEY}"
RECORD = ("Weekly bin collections will continue in the borough.", "The council agreed the budget for adult social "
          "care.", "A new cycle lane was approved on the high street.")


class Free:
    def price_for(self, model: str | None) -> Any:
        raise NotImplementedError

    def cost(self, usage: Usage | None, model: str | None) -> float:
        return 0.0


class SmallSite:
    """A site in a few lines: its record in an index, a model, a state database with the package's tables, its
    right of reply, and a pipeline from a question to a briefing that is saved, cached, costed and logged.

    ``leaks`` names what it gets wrong: "model", "embedder", "index", "events", "table" or "log" for a statement,
    "address", "visitor" or "question" for a reader."""

    def __init__(self, folder: Path, *leaks: str) -> None:
        self.leaks = leaks
        self.clock = FixedClock()
        self.state = StateDB(folder / "state.db", clock=self.clock,
                             migrations=(*usage.migrations(), *right_of_reply.migrations(),
                                         *observe.migrations()))
        case = SITES["councils"]
        self.replies = Replies(self.state, items=case.items(), rules=case.rules, messages=case.messages,
                               clock=self.clock)
        self.embedder = RecordingEmbedder()
        self.index = MemoryIndex(self.embedder)
        rows = [{"passage_id": f"p{n}", "record_id": f"r{n}", "source_key": "k", "heading": "", "text": text,
                 "search_text": text} for n, text in enumerate(RECORD)]
        self.index.replace(["k"], rows)
        self.index.add_vectors(["k"], [{k: r[k] for k in ("passage_id", "record_id", "source_key")} for r in rows],
                               self.embedder.embed_documents(list(RECORD)))
        self.model = ScriptedModel(recorded("cited_briefing"))
        self.lines: list[str] = []
        self.asked = 0

    def statements(self) -> list[str]:
        return [f"{s['name']}: {s['text']}" for s in self.replies.published(everywhere=True)]

    def ask(self, question: str, address: str = ADDRESS) -> Iterator[dict[str, Any]]:
        visitor = usage.visitor_code(self.state, address, clock=self.clock)
        said = self.statements()
        if "embedder" in self.leaks:
            self.embedder.embed_documents(said)
        if "index" in self.leaks:
            self.index.replace(["statements"], [{"passage_id": "s1", "record_id": "s1", "source_key": "statements",
                                                 "heading": "", "text": text, "search_text": text} for text in said])
        found = self.index.search_meaning(self.embedder.embed_query(question), None, 3)
        passages = [self.index.rows[row["passage_id"]]["text"] for row in found] + (said if "model" in self.leaks
                                                                                    else [])
        documents = tuple(Document(n, f"Source {n}", f"https://example.org/{n}", (text,))
                          for n, text in enumerate(passages, start=1))
        request = ModelRequest(model="a-model", instructions="Use only the sources.", question=question,
                               documents=documents)
        events: list[dict[str, Any]] = [{"type": "text", "text": e.text} for e in self.model.stream(request)
                                        if isinstance(e, TextDelta)]
        if "events" in self.leaks:
            events.append({"type": "text", "text": said[0]})
        events.append({"type": "final", "question": question})
        kept = [*events, {"type": "note", "text": said[0]}] if "table" in self.leaks else events
        self.asked += 1
        archive = usage.BriefingArchive(self.state, new_id=lambda: f"abc{self.asked:03d}", clock=self.clock)
        archive.save(question, {}, kept)
        usage.SqliteAnswerCache(self.state, clock=self.clock).put(usage.cache_key({"q": question}, length=64), events, 24)
        usage.Spending(self.state, Free(), clock=self.clock).add("answer", "a-model", Usage(), visitor=visitor)
        observe.SqliteBriefingLog(self.state, clock=self.clock).write(BriefingRecord(
            id=f"r{self.asked}", at=self.clock.now().isoformat(timespec="seconds"), outcome="completed",
            question=question, briefing_id=f"abc{self.asked:03d}", sources=len(found)))
        self.lines.append(json.dumps({"event": "briefing", "briefing": "abc123", "stage": "written", "ms": 310}))
        if "log" in self.leaks:
            self.lines.append(json.dumps({"event": "statements", "shown": said}))
        if "address" in self.leaks:
            self.state.set("last_address", address)
        if "visitor" in self.leaks:
            self.lines.append(json.dumps({"event": "briefing", "visitor": visitor}))
        if "question" in self.leaks:
            self.lines.append(json.dumps({"event": "asked", "question": question}))
            with self.state.connect() as con:
                con.execute("UPDATE wts_briefings SET options = ?", (json.dumps({"asked": question}),))
        yield from events

    def stays_out(self, **more: Any) -> None:
        assert_statements_stay_out(replies=self.replies, ask=self.ask, model=self.model, embedder=self.embedder,
                                   index=self.index, state=self.state, log_lines=lambda: self.lines,
                                   **{"item": ITEM, "question": QUESTION, **more})

    def visitor(self) -> str:
        return usage.visitor_code(self.state, ADDRESS, clock=self.clock)


# Statements stay out


def test_a_site_that_keeps_statements_apart_passes(tmp_path):
    site = SmallSite(tmp_path)
    site.stays_out(random=FixedRandom(["0a1b2c3d4e5f"]))
    # the check did what it says: a statement carrying the marker was published, and the question was asked
    shown = site.replies.published(everywhere=True)
    assert len(shown) == 1 and "wtsmarker0a1b2c3d4e5f" in shown[0]["text"] and shown[0]["item"] == ITEM
    assert site.replies.statements()[0]["email"] == "wtsmarker0a1b2c3d4e5f@example.org"
    assert [r.question for r in site.model.requests] == [QUESTION] and QUESTION in site.embedder.queries
    site.stays_out()  # and again, with a marker made by chance: a second statement, a second question
    assert len(site.model.requests) == 2


@pytest.mark.parametrize("leak, where", [
    ("model", r"a request to the model \(1 of 1\)"),
    ("index", r"the index \(a row in it, or written to it\)"),
    ("table", r"wts_briefings\.events"),
    ("log", r"a log line: \{\"event\": \"statements\""),
])
def test_a_site_that_lets_a_statement_through_fails(tmp_path, leak, where):
    """The rule: statements under the right of reply never reach the model, the search index or the record.
    One deliberately leaky pipeline for each: the model's request, the index, a table, a log line."""
    site = SmallSite(tmp_path, leak)
    with pytest.raises(AssertionError, match="a statement under the right of reply reached where it must never be:\n"
                                             f"  {where}"):
        site.stays_out()


@pytest.mark.parametrize("leak, where", [("embedder", "a text given to the embedder"),
                                         ("events", "an event sent to the reader")])
def test_the_embedder_and_what_the_reader_is_sent_are_watched_too(tmp_path, leak, where):
    with pytest.raises(AssertionError, match=where):
        SmallSite(tmp_path, leak).stays_out()


def test_every_place_a_statement_reached_is_named(tmp_path):
    site = SmallSite(tmp_path, "model", "embedder", "index", "events", "table", "log")
    with pytest.raises(AssertionError) as failed:
        site.stays_out()
    said = str(failed.value)
    for where in ("a request to the model", "a text given to the embedder", "the index (a row in it, or written",
                  "an event sent to the reader", "wts_briefings.events", "wts_answer_cache.events", "a log line"):
        assert where in said, where
    assert "wts_statements" not in said and "wts_statement_log" not in said  # where a statement belongs


def test_a_check_that_proves_nothing_fails(tmp_path):
    site = SmallSite(tmp_path)
    with pytest.raises(AssertionError, match="the question never reached the model, so this proves nothing"):
        assert_statements_stay_out(replies=site.replies, ask=lambda question: iter(()), model=site.model,
                                   embedder=site.embedder, index=site.index, state=site.state, log_lines=[],
                                   item=ITEM, question=QUESTION)
    site.replies.hide(ITEM, "Under review.")
    with pytest.raises(right_of_reply.Refused):  # nothing can be sent beside a hidden item: the site's own words
        site.stays_out()
    with pytest.raises(right_of_reply.Refused):
        site.stays_out(item="/not-an-item")


class TheSitesOwn:
    """What a site on its real model client and its real index hands the check: three things of its own that say
    what the stand-ins say (``ModelSeen``, ``EmbedderSeen``, ``IndexSeen``), and are none of them."""

    def __init__(self, site: SmallSite) -> None:
        self._site = site

    @property
    def requests(self) -> list[Any]:  # what the site's faked SDK was sent
        return [repr(r) for r in self._site.model.requests]

    @property
    def structured_requests(self) -> list[Any]:
        return []

    @property
    def texts(self) -> tuple[str, ...]:
        return tuple(self._site.embedder.texts)

    def everything(self) -> Iterator[dict[str, Any]]:  # as a real index gives its rows
        yield from self._site.index.rows.values()


@pytest.mark.parametrize("leak, where", [(None, None), ("model", "a request to the model"),
                                         ("embedder", "a text given to the embedder"),
                                         ("index", r"the index \(a row in it, or written to it\)")])
def test_the_check_reads_anything_that_can_say_what_the_stand_ins_say(tmp_path, leak, where):
    """Found by Where Councils Stand's fixes: the three were typed as the package's own stand-ins, so a site on a
    real index wrote look-alike classes to satisfy the type. They are read through three small interfaces."""
    site = SmallSite(tmp_path, *([leak] if leak else []))
    own = TheSitesOwn(site)

    def check() -> None:
        assert_statements_stay_out(replies=site.replies, ask=site.ask, model=own, embedder=own, index=own,
                                   state=site.state, log_lines=lambda: site.lines, item=ITEM, question=QUESTION)

    if where is None:
        check()
    else:
        with pytest.raises(AssertionError, match=where):
            check()


def test_an_index_look_alike_written_for_the_earlier_version_is_still_read(tmp_path):
    """One with ``rows``, ``vector_rows`` and ``added`` and no ``everything``: the adopted sites' tests have them."""
    class LookAlike:
        def __init__(self, index: MemoryIndex) -> None:
            self.index = index

        rows = property(lambda self: self.index.rows)
        vector_rows = property(lambda self: self.index.vector_rows)
        added = property(lambda self: self.index.added)

    site = SmallSite(tmp_path, "index")
    with pytest.raises(AssertionError, match=r"the index \(its rows\)\n  the index \(a row written to it\)"):
        assert_statements_stay_out(replies=site.replies, ask=site.ask, model=site.model, embedder=site.embedder,
                                   index=LookAlike(site.index), state=site.state, log_lines=lambda: site.lines,
                                   item=ITEM, question=QUESTION)


def test_whom_it_speaks_for_is_passed_on_where_a_site_must_be_told(tmp_path):
    site = SmallSite(tmp_path)
    site.stays_out(item="/b/abc123", about=BARNSLEY)
    assert site.replies.published(about=BARNSLEY)[0]["item"] == "/b/abc123"


# Nothing about readers


def asked(tmp_path: Path, *leaks: str) -> SmallSite:
    site = SmallSite(tmp_path, *leaks)
    list(site.ask(QUESTION))
    usage.Failures(site.state, clock=site.clock).note("answer", QUESTION, "RuntimeError")
    site.replies.report(kind="error", page="/votes/x", message="Something is wrong here.", visitor=site.visitor())
    return site


def test_a_site_that_keeps_only_what_its_notice_says_passes(tmp_path):
    site = asked(tmp_path)
    assert_no_reader_data(site.state, site.lines, question=QUESTION, address=ADDRESS, visitor=site.visitor())
    assert_no_reader_data(site.state, site.lines, question=QUESTION, address=ADDRESS)
    # the question and the visitor's code are kept, and only where they may be
    with site.state.connect() as con:
        rows = {table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("wts_briefings", "wts_answer_cache", "wts_briefing_log", "wts_failures", "wts_spending",
                              "wts_reply_counts")}
    assert all(rows.values()), rows


@pytest.mark.parametrize("leak, where", [
    ("address", "the address is in wts_kv.value"),
    ("visitor", "the visitor is in a log line"),
    ("question", "the question is in wts_briefings.options\n  the question is in a log line"),
])
def test_a_site_that_keeps_more_fails(tmp_path, leak, where):
    site = asked(tmp_path, leak)
    with pytest.raises(AssertionError, match="something about a reader is kept where it should not be:\n"
                                             f"  {where}"):
        assert_no_reader_data(site.state, site.lines, question=QUESTION, address=ADDRESS, visitor=site.visitor())


def test_a_question_is_found_as_json_writes_it_and_whatever_its_case(tmp_path):
    site = SmallSite(tmp_path)
    question = 'Did the leader say "no cuts" in Übersee?'
    list(site.ask(question))
    site.lines.append(json.dumps({"event": "asked", "q": question.upper()}))  # quotes and letters escaped
    with pytest.raises(AssertionError, match="the question is in a log line"):
        assert_no_reader_data(site.state, site.lines, question=question, address=ADDRESS)


def test_the_visitors_code_is_allowed_only_in_its_own_columns(tmp_path):
    site = asked(tmp_path)
    with site.state.connect() as con:
        con.execute("UPDATE wts_spending SET model = ?", (site.visitor(),))
        con.execute("INSERT INTO wts_failures (at, kind, question, error) VALUES ('2026', 'answer', '', ?)",
                    (f"limit reached for {site.visitor()}",))
    with pytest.raises(AssertionError, match="the visitor is in wts_failures.error\n  the visitor is in "
                                             "wts_spending.model"):
        assert_no_reader_data(site.state, site.lines, question=QUESTION, address=ADDRESS, visitor=site.visitor())


def test_a_site_with_no_questions_checks_the_address_and_the_visitors_code_alone(tmp_path):
    """Where Landlords Stand writes no briefings: its readers search, and it had to pass search words as a
    "question". With none given, the address and the code are checked just the same."""
    site = asked(tmp_path)
    assert_no_reader_data(site.state, site.lines, address=ADDRESS, visitor=site.visitor())
    assert_no_reader_data(site.state, site.lines, address=ADDRESS)
    leaking = asked(tmp_path / "leaking", "address")
    with pytest.raises(AssertionError, match="the address is in wts_kv.value"):
        assert_no_reader_data(leaking.state, leaking.lines, address=ADDRESS)
    with pytest.raises(TypeError, match="address"):  # the address is what every site has: it is always given
        assert_no_reader_data(site.state, site.lines)


@pytest.mark.parametrize("short", [{"question": "bins"}, {"address": "::1"}, {"visitor": "abc"}])
def test_something_too_short_to_prove_anything_is_refused(tmp_path, short):
    site = asked(tmp_path)
    with pytest.raises(ValueError, match="too short to prove anything"):
        assert_no_reader_data(site.state, site.lines, **{"question": QUESTION, "address": ADDRESS, **short})


# The helpers themselves keep the wall


def test_nothing_near_the_model_loads_the_right_of_reply_by_importing_the_test_helpers():
    """``wts_core.eval`` reads the recording format in ``wts_core.testing.models``. Importing that, or the package
    it is in, must not bring ``wts_core.replies`` with it: the two checks here are imported only when asked for."""
    import subprocess
    import sys

    code = ("import sys\n"
            "import wts_core.testing, wts_core.testing.models, wts_core.testing.index\n"
            "import wts_core.eval, wts_core.observe, wts_core.checks\n"
            "print(sorted(m for m in sys.modules if m.startswith('wts_core.replies')))\n"
            "from wts_core.testing import assert_no_reader_data, assert_statements_stay_out, golden\n"
            "print('wts_core.replies' in sys.modules)")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert (done.returncode, done.stdout.split()) == (0, ["[]", "True"]), done.stderr


# A briefing's record is tied to no one once its day is over (0.3.0)


class WithAccounts:
    """A site with signed-in accounts (Where MPs Stand), through the real desk: two accounts and a member of the
    public each ask a question in the same hour, and their briefings are written, recorded and paid for."""

    def __init__(self, folder: Path) -> None:
        from test_briefing_desk import Told
        from test_usage_sites import MPS
        from wts_core.usage import Limits

        self.clock_start = "2026-11-12T10:07:31+00:00"
        self.state: StateDB | None = None
        told = Told(MPS, folder, limits=Limits(per_visitor_daily=9, per_account_daily=9, daily_cap_usd=50.0,
                                                monthly_cap_usd=500.0))
        told.clock.set(self.clock_start)
        told.db = StateDB(told.db.path, migrations=(*usage.migrations(), *observe.migrations()), clock=told.clock)
        log = observe.SqliteBriefingLog(told.db, clock=told.clock)
        told.desk._log = log  # the real record, where the desk's own tests keep a list
        self.told, self.log, self.state, self.clock = told, log, told.db, told.clock
        for n, (visitor, account) in enumerate((("c" * 24, 7), ("e" * 24, 8), ("a" * 24, None))):
            told.clock.advance(minutes=3, seconds=n)
            told.run(visitor=visitor, account=account, cache_key=None,
                     question=f"A question only asker {n} asked, about bins on route {n}?")


def test_within_its_day_a_record_can_be_matched_to_who_asked_and_the_check_says_so_only_of_past_days(tmp_path):
    site = WithAccounts(tmp_path)
    # today: the spending rows name the code and the account (the daily limits count by them), and the check,
    # which promises nothing of today, passes
    assert_briefings_tied_to_no_one(site.state, clock=site.clock)
    with site.state.connect() as con:
        assert {r[0] for r in con.execute("SELECT at FROM wts_briefing_log")} == {"2026-11-12T10:00:00+00:00"}
        assert {r[0] for r in con.execute("SELECT account FROM wts_spending")} == {7, 8, None}


def test_once_its_day_is_over_no_record_can_be_matched_to_a_visitor_or_an_account_by_time_or_by_counts(tmp_path):
    """The joins the independent reviews made, tried on the day after: they give nothing. The record's time is
    its hour, a spending row's is its day, and no row says whose it was, or even that it was an account's."""
    site = WithAccounts(tmp_path)
    site.clock.advance(days=1)
    with pytest.raises(AssertionError) as tied:  # the night's tidy has not run yet: the joins still work
        assert_briefings_tied_to_no_one(site.state, clock=site.clock)
    for found in ("6 rows of wts_spending from before 2026-11-13 still hold a visitor's code",
                  "4 rows of wts_spending from before 2026-11-13 still say they were a signed-in account's "
                  "(account: 7,8)",
                  "6 rows of wts_spending from before 2026-11-13 keep their time finer than the day (such as "
                  "2026-11-12T10:10:31+00:00)"):
        assert found in str(tied.value)
    usage.forget_visitors(site.state, clock=site.clock)  # what the nightly tidy does, and the day's first model call
    assert_briefings_tied_to_no_one(site.state, clock=site.clock)
    assert split_by_account_totals(site.state, clock=site.clock) == {}
    # what is left of the accounts: each one's calls and cost for the month, for the owner's report
    with site.state.connect() as con:
        assert [tuple(r) for r in con.execute("SELECT month, account, calls FROM wts_account_months ORDER BY 2")] == [
            ("2026-11", 7, 2), ("2026-11", 8, 2)]
        assert {tuple(r) for r in con.execute("SELECT at, visitor, account FROM wts_spending")} == {
            ("2026-11-12T00:00:00+00:00", "", None)}
        assert {r[0] for r in con.execute("SELECT question FROM wts_briefing_log")} == {
            f"A question only asker {n} asked, about bins on route {n}?" for n in range(3)}  # the questions are kept


class ADay:
    """A day on a site with signed-in accounts, as the independent review of 0.3.0 made one for its attack: so
    many accounts and so many visitors, each asking one to four briefings (a question read by a small model, a
    briefing written by a large one) with token counts drawn at random. Who asked what is kept here, to mark the
    attack by; the database is then left as the night leaves it."""

    def __init__(self, folder: Path, *, accounts: int, visitors: int, seed: int = 0, forget: bool = True) -> None:
        import random

        from wts_core.ports import Price

        rng = random.Random(seed)
        self.clock = FixedClock("2026-11-15T07:00:00+00:00")
        self.state = StateDB(folder / f"day{accounts}-{visitors}-{seed}.db",
                             migrations=(*usage.migrations(), *observe.migrations()), clock=self.clock)
        prices = usage.PriceTable(base=Price(3.0, 15.0, 0.3), models=(("small", Price(1.0, 5.0, 0.1)),))
        spending = usage.Spending(self.state, prices, clock=self.clock)
        log = observe.SqliteBriefingLog(self.state, clock=self.clock)
        self.whose: dict[str, int | None] = {}
        askers: list[int | str] = [n for n in range(1, accounts + 1) for _ in range(rng.randint(1, 4))]
        askers += [f"code{n:02d}" * 4 for n in range(visitors) for _ in range(rng.randint(1, 3))]
        rng.shuffle(askers)
        for n, who in enumerate(askers):
            self.clock.advance(seconds=rng.randint(20, 400))
            to = {"account": who, "visitor": f"acct{who:02d}" * 4} if isinstance(who, int) else {"visitor": who}
            read = Usage(input_uncached=rng.randint(600, 900), output=rng.randint(40, 120))
            written = Usage(input_uncached=rng.randint(200, 800), cache_read=rng.randint(8000, 30000),
                            output=rng.randint(350, 1400))
            cost = spending.add("parse", "small", read, **to) + spending.add("answer", "big", written, **to)
            counts = (read + written).as_stored()
            log.write(BriefingRecord(
                id=f"r{n:04d}", at=self.clock.now().isoformat(), outcome="completed", question=f"question {n}",
                input_tokens=counts["input_tokens"], cache_read_tokens=counts["cache_read_tokens"],
                output_tokens=counts["output_tokens"], cost_usd=round(cost, 6)))
            self.whose[f"r{n:04d}"] = who if isinstance(who, int) else None
        with self.state.connect() as con:  # what the rows said while their day lasted
            self.rows = [tuple(r) for r in con.execute("SELECT id, at, account, cost_usd FROM wts_spending")]
        self.clock.set("2026-11-16T03:00:00+00:00")
        if forget:
            usage.forget_earlier_days(self.state, clock=self.clock)
            self.state.compact()

    @property
    def accounts(self) -> dict[str, int]:
        return {record: who for record, who in self.whose.items() if who is not None}

    def as_first_mended(self) -> None:
        """Put the database as the first mend of 0.3.0 left it after the night, which the review took apart: a
        row that was an account's says "some account" (0), and each account's exact total for the day is kept."""
        with self.state.connect() as con:
            con.executemany("UPDATE wts_spending SET account = 0 WHERE id = ?",
                            [(rid,) for rid, _, account, _ in self.rows if account is not None])
            con.execute("CREATE TABLE wts_account_days (day TEXT NOT NULL, account INTEGER NOT NULL, "
                        "cost_usd REAL NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0, "
                        "PRIMARY KEY (day, account))")
            totals: dict[int, list[float]] = {}
            for _, _, account, cost in self.rows:
                if account is not None:
                    total = totals.setdefault(account, [0.0, 0])
                    total[0], total[1] = total[0] + cost, total[1] + 1
            con.executemany("INSERT INTO wts_account_days VALUES ('2026-11-15', ?, ?, ?)",
                            [(account, cost, calls) for account, (cost, calls) in totals.items()])
            con.execute("DELETE FROM wts_account_months")


@pytest.mark.parametrize(("accounts", "visitors"), [(1, 30), (3, 40), (6, 40), (9, 60)])
def test_the_reviews_attack_gives_no_briefing_to_an_account(tmp_path, accounts, visitors):
    """The attack the independent review of 0.3.0 made, at the sizes it made it. Against the first mend it gave
    back every briefing of one account among thirty visitors, and 324 of 447 with nine accounts, none wrongly.
    Against what is kept now, in a month that is one day old (the worst case for one copy of the database), it
    gives none. scripts/measure_account_split.py runs it twenty times at each size, and on quiet sites."""
    day = ADay(tmp_path, accounts=accounts, visitors=visitors)
    assert len(day.accounts) >= accounts
    assert split_by_account_totals(day.state, clock=day.clock) == {}
    assert_briefings_tied_to_no_one(day.state, clock=day.clock)


def test_the_check_would_have_caught_the_first_mend(tmp_path):
    """The check that shipped with the first mend passed on a database the review then took apart. This one is
    given that database: it names the mark left on the rows and the totals kept by the day, and its own attack
    gives the accounts their briefings back, as the review's did."""
    day = ADay(tmp_path, accounts=3, visitors=40)
    day.as_first_mended()
    given = split_by_account_totals(day.state, clock=day.clock)
    assert given and all(day.whose[record] == account for record, account in given.items())  # none wrongly
    assert len(given) >= 0.8 * len(day.accounts)  # and nearly all (the review: 152 of 155 at this size)
    with pytest.raises(AssertionError) as tied:
        assert_briefings_tied_to_no_one(day.state, clock=day.clock)
    for found in ("still say they were a signed-in account's (account: 0)",
                  "wts_account_days keeps each account's total by the day",
                  f"{len(given)} rows of wts_briefing_log from before 2026-11-16 are given to one signed-in account "
                  "by the totals kept for it"):
        assert found in str(tied.value)


def test_a_month_in_which_an_account_was_alone_is_its_own_and_the_check_says_so(tmp_path):
    """What is not promised, shown and not hidden: where the only briefings of a month are one account's, its
    month's total is made up of them and of nothing else. The check fails on such a database, and says what a
    test should do about it."""
    day = ADay(tmp_path, accounts=1, visitors=0)
    given = split_by_account_totals(day.state, clock=day.clock)
    assert given == day.accounts and len(given) >= 1
    with pytest.raises(AssertionError, match="are the only ones that could make up its month: a test should have "
                                             "another asker's beside them"):
        assert_briefings_tied_to_no_one(day.state, clock=day.clock)


def test_a_spending_row_kept_to_the_second_gives_every_record_its_second_back_and_is_caught(tmp_path):
    """The review's second join. The record keeps its hour; a spending row kept its second, for good, and has the
    same token counts: so every record got its second back (139 of 139 in the review's database). A row of a day
    that is over now keeps the day alone."""
    day = ADay(tmp_path, accounts=2, visitors=20)
    assert_briefings_tied_to_no_one(day.state, clock=day.clock)
    with day.state.connect() as con:
        assert {r[0] for r in con.execute("SELECT at FROM wts_spending")} == {"2026-11-15T00:00:00+00:00"}
        con.executemany("UPDATE wts_spending SET at = ? WHERE id = ?", [(at, rid) for rid, at, _, _ in day.rows])
    with pytest.raises(AssertionError) as tied:  # as 0.2.1 and the first mend kept them
        assert_briefings_tied_to_no_one(day.state, clock=day.clock)
    assert f"{len(day.rows)} rows of wts_spending from before 2026-11-16 keep their time finer than the day" in str(
        tied.value)
    assert (f"{len(day.whose)} rows of wts_briefing_log from before 2026-11-16 are given a second by the spending "
            "rows whose token counts add up to theirs") in str(tied.value)


def test_an_accounts_month_kept_more_finely_than_the_cent_is_caught(tmp_path):
    day = ADay(tmp_path, accounts=2, visitors=20)
    with day.state.connect() as con:
        con.execute("UPDATE wts_account_months SET cost_usd = cost_usd + 0.001234 WHERE account = 1")
        con.execute("INSERT INTO wts_visitor_days (day, who, visitors) VALUES ('2026-11-15', '1', 1)")
    with pytest.raises(AssertionError) as tied:
        assert_briefings_tied_to_no_one(day.state, clock=day.clock)
    assert "1 rows of wts_account_months are kept more finely than the month and the cent" in str(tied.value)
    assert "1 rows of wts_visitor_days count an account's visitors" in str(tied.value)


def test_a_record_kept_to_the_second_is_caught(tmp_path):
    site = WithAccounts(tmp_path)
    site.clock.advance(days=1)
    usage.forget_visitors(site.state, clock=site.clock)
    with site.state.connect() as con:  # as a version before 0.3.0 wrote it, or a site's own code might
        con.execute("UPDATE wts_briefing_log SET at = '2026-11-12T10:13:32+00:00' WHERE rowid = 1")
    with pytest.raises(AssertionError, match="1 rows of wts_briefing_log keep their time finer than the hour "
                                             r"\(such as 2026-11-12T10:13:32\+00:00\)"):
        assert_briefings_tied_to_no_one(site.state, clock=site.clock)
    with pytest.raises(AssertionError, match="no record of briefings"):
        assert_briefings_tied_to_no_one(StateDB(tmp_path / "bare.db"), clock=site.clock)


def test_a_records_second_can_come_only_from_tables_that_say_nothing_of_who(tmp_path):
    """Found by the second independent review of 0.3.0: "no time finer than the hour can be given back from the
    package's tables" was too wide. The answer cache (for its hours), a note of a failed briefing (90 days) and a
    saved briefing (for good) each keep the second they were stored, and a record is matched to them by its
    question or its briefing. What is true, and held here: the spending rows give no second back, and none of
    those three tables says who. A column that did would fail the check."""
    site = WithAccounts(tmp_path)
    site.clock.advance(days=2)
    usage.forget_earlier_days(site.state, clock=site.clock)
    assert_briefings_tied_to_no_one(site.state, clock=site.clock)
    with site.state.connect() as con:
        # the seconds are there, as documented: in the saved briefings and the cache, and nowhere in the spending
        saved = {r[0] for r in con.execute("SELECT created_at FROM wts_briefings")}
        cached = {r[0] for r in con.execute("SELECT created_at FROM wts_answer_cache")}
        assert saved and all(not at.endswith(":00:00+00:00") for at in saved | cached)
        assert {r[0] for r in con.execute("SELECT at FROM wts_spending")} == {"2026-11-12T00:00:00+00:00"}
        assert {r[0] for r in con.execute("SELECT at FROM wts_briefing_log")} == {"2026-11-12T10:00:00+00:00"}
        for table in ("wts_briefings", "wts_answer_cache", "wts_failures"):
            assert not {r[1] for r in con.execute(f"PRAGMA table_info({table})")} & {"visitor", "account"}
        con.execute("ALTER TABLE wts_failures ADD COLUMN visitor TEXT")  # as a careless change to the package might
    with pytest.raises(AssertionError, match="wts_failures keeps the second a row was stored and has a column "
                                             r"that says who \(visitor\)"):
        assert_briefings_tied_to_no_one(site.state, clock=site.clock)


def test_a_record_that_is_in_every_way_of_making_up_an_accounts_total_is_given_to_it(tmp_path):
    """The second review of 0.3.0: the package's attack gave a record to an account only when ONE set of records
    fitted the account's total. A record that is in every set that fits is the account's just as surely, and on
    a quiet site that was more than twice as many (9 against 4 with one account among two visitors)."""
    from wts_core.ports import Price

    clock = FixedClock("2026-11-12T09:00:00+00:00")
    state = StateDB(tmp_path / "state.db", migrations=(*usage.migrations(), *observe.migrations()), clock=clock)
    spending = usage.Spending(state, usage.PriceTable(base=Price(2.0, 10.0, 0.2)), clock=clock)
    log = observe.SqliteBriefingLog(state, clock=clock)
    # the account asks two briefings, of 5 cents and of 2; a member of the public asks one of 2.01 cents
    for record, tokens, who in (("dear", 25_000, {"account": 7}), ("cheap", 10_000, {"account": 7}),
                                ("public", 10_050, {"visitor": "v" * 24})):
        clock.advance(minutes=7)
        cost = spending.add("answer", "m", Usage(input_uncached=tokens), **who)
        log.write(BriefingRecord(id=record, at=clock.now().isoformat(), outcome="completed", question=f"{record}?",
                                 input_tokens=tokens, cost_usd=cost))
    clock.advance(days=1)
    usage.forget_earlier_days(state, clock=clock)
    with state.connect() as con:
        assert [tuple(r) for r in con.execute("SELECT account, cost_usd, calls FROM wts_account_months")] == [(7, 0.07, 2)]
    # two sets of two come to 7 cents within half a cent: the dear one with either of the others. So which of
    # the cheap two was the account's cannot be told; and the dear one was, whichever it is.
    unsettled: list[tuple[str, int]] = []
    assert split_by_account_totals(state, clock=clock, unsettled=unsettled) == {"dear": 7} and unsettled == []
    with pytest.raises(AssertionError, match="1 rows of wts_briefing_log from before 2026-11-13 are given to one "
                                             r"signed-in account by the totals kept for it \(dear to account 7\)"):
        assert_briefings_tied_to_no_one(state, clock=clock)
