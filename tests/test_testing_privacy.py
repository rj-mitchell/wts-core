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
from wts_core.testing import FixedClock, FixedRandom, assert_no_reader_data, assert_statements_stay_out
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


# ---- statements stay out -------------------------------------------------------------------------------------------


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
    ("index", r"the index \(its rows\)\n  the index \(a row written to it\)"),
    ("table", r"wts_briefings\.events"),
    ("log", r"a log line: \{\"event\": \"statements\""),
])
def test_a_site_that_lets_a_statement_through_fails(tmp_path, leak, where):
    """The brief's Must: statements under the right of reply never reach the model, the search index or the record.
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
    for where in ("a request to the model", "a text given to the embedder", "the index (its rows)",
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


def test_whom_it_speaks_for_is_passed_on_where_a_site_must_be_told(tmp_path):
    site = SmallSite(tmp_path)
    site.stays_out(item="/b/abc123", about=BARNSLEY)
    assert site.replies.published(about=BARNSLEY)[0]["item"] == "/b/abc123"


# ---- nothing about readers -----------------------------------------------------------------------------------------


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


# ---- the helpers themselves keep the wall --------------------------------------------------------------------------


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
