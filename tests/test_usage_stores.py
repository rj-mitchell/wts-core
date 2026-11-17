"""What is kept: the answer cache, saved briefings and notes of failures. The sites' own tests, on the package's
tables."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date

import pytest

from test_usage_sites import site  # noqa: F401  (the fixture)
from wts_core import usage
from wts_core.state import StateDB
from wts_core.testing import FixedClock, FixedRandom
from wts_core.usage import (
    BriefingArchive,
    BriefingListing,
    Failures,
    SavedBriefing,
    SqliteAnswerCache,
    alphabet_id,
    cache_key,
    token_id,
)

MPS_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # Where MPs Stand's: no 0/o or 1/l
MPS_ID = re.compile(r"^[a-km-z2-9]{10}$")


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock("2026-11-13T12:00:00+00:00")


@pytest.fixture
def db(tmp_path, clock) -> StateDB:
    return StateDB(tmp_path / "state.db", migrations=usage.migrations(), clock=clock)


def test_the_tables_are_the_packages_own_and_made_once(tmp_path, clock):
    db = StateDB(tmp_path / "state.db", migrations=usage.migrations(), clock=clock)
    mine = {"wts_spending", "wts_answer_cache", "wts_briefings", "wts_failures"}
    assert mine <= db.tables() and all(10 <= m.number <= 19 for m in usage.migrations())
    Failures(db, clock=clock).note("briefing", "q", "e")
    again = StateDB(tmp_path / "state.db", migrations=usage.migrations(), clock=clock)   # the next start
    assert len(Failures(again, clock=clock).recent()) == 1
    # Migrations only add. Two take something away, and on purpose (0.3.0): what 0.2.x kept about an account by
    # the day is gathered into its month, and the time of day goes from the spending rows of days gone by.
    takes_away = {"account_months": 3, "spending_to_the_day": 1}
    for m in usage.migrations():
        other = [s for s in m.statements
                 if not s.startswith(("CREATE TABLE IF NOT EXISTS wts_", "CREATE INDEX IF NOT EXISTS wts_"))]
        assert len(other) == takes_away.get(m.name, 0), m.name
        assert all(s.startswith(("INSERT INTO wts_", "DELETE FROM wts_", "UPDATE wts_")) for s in other)


# The answer cache


def test_the_cache_key_is_a_hash_of_the_parts_whatever_their_order(site):  # noqa: F811
    parts = {"q": "what has been said about trial by jury?", "mode": "summary", "plan": None, "history": [],
             "sources_only": False, "model": "claude-sonnet-5-5", "data": 1731492000}
    key = cache_key(parts, length=site.key_length)
    assert len(key) == site.key_length and key == cache_key(dict(reversed(parts.items())), length=site.key_length)
    assert key == hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:site.key_length]
    assert cache_key(parts, length=64).startswith(key) and len(cache_key(parts, length=64)) == 64
    # another mode, or newer data, is another answer
    assert cache_key({**parts, "mode": "comprehensive"}, length=site.key_length) != key
    assert cache_key({**parts, "data": 1731578400}, length=site.key_length) != key
    # what JSON cannot write is written as its text
    assert cache_key({"data": date(2026, 11, 13)}, length=64) == cache_key({"data": "2026-11-13"}, length=64)
    with pytest.raises(TypeError):
        cache_key(parts)  # type: ignore[call-arg]  # the sites differ, so the length is always said


def test_repeat_questions_come_from_the_cache(site, db, clock):  # noqa: F811
    """The sites' tests of a repeated question: the same parts give the events back, others give nothing."""
    cache = SqliteAnswerCache(db, clock=clock)
    hours = site.usage["answer_cache_hours"]
    events = [{"type": "plan", "plan": {"search_text": "trial by jury"}}, {"type": "sources", "sources": [{"n": 1}]},
              {"type": "text", "text": "Some “curly” words."},
              {"type": "final", "answer": {"citations_total": 1, "new_field": [1, 2]}, "briefing_id": "abc"}]
    key = cache_key({"q": "trial by jury", "mode": "summary"}, length=site.key_length)
    assert cache.get(key, hours) is None
    cache.put(key, events, hours)
    assert cache.get(key, hours) == events                               # unknown keys pass through untouched
    assert cache.get(cache_key({"q": "trial by jury", "mode": "comprehensive"}, length=site.key_length), hours) is None
    cache.put(key, [{"type": "final", "answer": None}], hours)           # the same key again replaces it
    assert cache.get(key, hours) == [{"type": "final", "answer": None}]


def test_an_answer_is_given_until_it_is_too_old(site, db, clock):  # noqa: F811
    cache = SqliteAnswerCache(db, clock=clock)
    hours = site.usage["answer_cache_hours"]
    assert hours == 168
    cache.put("k", [{"type": "final"}], hours)
    clock.advance(hours=hours - 1)
    assert cache.get("k", hours) == [{"type": "final"}]
    clock.advance(hours=1)
    assert cache.get("k", hours) == [{"type": "final"}]                  # exactly a week old: still given
    clock.advance(1)
    assert cache.get("k", hours) is None
    assert cache.get("k", hours + 1) == [{"type": "final"}]              # it is there until the next store


def test_no_hours_means_no_cache(db, clock):
    """Where Councils Stand turns its cache off this way; the other two never ask the cache when the hours are 0."""
    cache = SqliteAnswerCache(db, clock=clock)
    cache.put("k", [{"type": "final"}], 0)
    assert cache.get("k", 0) is None and cache.get("k", -1) is None
    assert cache.get("k", 1) == [{"type": "final"}]


def test_old_answers_are_deleted_from_the_cache(db, clock):
    """Where Councils Stand's test: they are never read again, and would otherwise fill the database."""
    cache = SqliteAnswerCache(db, clock=clock)
    with db.connect() as con:
        con.execute("INSERT INTO wts_answer_cache (key, created_at, events) "
                    "VALUES ('old', '2026-01-01T00:00:00+00:00', '[]')")
    cache.put("new", [{"type": "final"}], max_hours=168)
    with db.connect() as con:
        assert [r["key"] for r in con.execute("SELECT key FROM wts_answer_cache")] == ["new"]
    clock.advance(hours=168)
    cache.put("newer", [], max_hours=168)                                # exactly a week old is kept
    clock.advance(1)
    cache.put("newest", [], max_hours=168)
    with db.connect() as con:
        assert sorted(r["key"] for r in con.execute("SELECT key FROM wts_answer_cache")) == ["newer", "newest"]


def test_a_cached_answer_is_dropped_by_its_key(db, clock):
    """For a site whose briefing was withdrawn or hidden: the next reader with the same question must not be
    played what was taken down. Before 0.2.1 the cache could only be looked in and added to."""
    cache = SqliteAnswerCache(db, clock=clock)
    cache.put("a" * 64, [{"type": "final", "briefing_id": "kept4567"}], 168)
    cache.put("b" * 64, [{"type": "final", "briefing_id": "gone1234"}], 168)
    assert cache.delete("b" * 64) is True
    assert cache.get("b" * 64, 168) is None and cache.get("a" * 64, 168) is not None
    assert cache.delete("b" * 64) is False and cache.delete("never there") is False


def test_every_cached_copy_of_a_briefing_is_dropped_by_the_briefings_id(db, clock):
    """A command that withdraws a briefing knows its id, not the key its question was cached under; and one
    briefing may be cached under more than one key (Where MPs Stand puts an old answer back under its key)."""
    cache = SqliteAnswerCache(db, clock=clock)

    def replay(briefing_id: str | None, text: str = "The motion was lost.") -> list[dict]:
        return [{"type": "plan", "plan": {}}, {"type": "sources", "sources": [{"n": 1}]},
                {"type": "text", "text": text}, {"type": "final", "answer": {}, "briefing_id": briefing_id}]

    cache.put("a" * 64, replay("gone1234"), 168)
    cache.put("b" * 64, replay("gone1234"), 168)
    cache.put("c" * 64, replay("kept4567"), 168)
    cache.put("d" * 64, replay(None), 168)  # "no records": cached, never saved
    cache.put("e" * 64, replay("kept9999", text='A briefing that quotes the id "gone1234" in its words.'), 168)
    assert cache.delete_briefing("gone1234") == 2
    assert [cache.get(k * 64, 168) is not None for k in "abcde"] == [False, False, True, True, True]
    assert cache.delete_briefing("gone1234") == 0 and cache.delete_briefing("") == 0
    odd = 'an "odd" id\u00e9'  # found however JSON wrote it
    cache.put("f" * 64, replay(odd), 168)
    assert cache.delete_briefing(odd) == 1


def test_the_desks_interface_for_a_cache_asks_for_no_more_than_the_desk_uses():
    """``delete`` is the class's own: a site's cache of its own kind need not have it for the desk to use it."""
    from wts_core.ports import AnswerCache

    assert {name for name in vars(AnswerCache) if not name.startswith("_")} == {"get", "put"}


def test_sources_that_carry_dates_are_kept_as_text(db, clock):
    """Where Countries Stand: a General Assembly vote's source has a date object, which plain JSON cannot write."""
    cache = SqliteAnswerCache(db, clock=clock)
    cache.put("k", [{"type": "sources", "sources": [{"voted_on": date(2024, 12, 17)}]}], 168)
    assert cache.get("k", 168) == [{"type": "sources", "sources": [{"voted_on": "2024-12-17"}]}]
    with db.connect() as con:
        row = con.execute("SELECT created_at, events FROM wts_answer_cache").fetchone()
    assert row["created_at"] == "2026-11-13T12:00:00+00:00"
    assert row["events"] == '[{"type": "sources", "sources": [{"voted_on": "2024-12-17"}]}]'


# Saved briefings


def url_ids(db: StateDB, clock: FixedClock, ids=()) -> BriefingArchive:
    """An archive with ids as Where Countries Stand and Where Councils Stand make them (or the ones given)."""
    chance = FixedRandom(tokens=list(ids))
    return BriefingArchive(db, new_id=lambda: token_id(8, random=chance), clock=clock)


EVENTS = [{"type": "plan", "plan": {"search_text": "climate finance"}}, {"type": "sources", "sources": [{"n": 1}]},
          {"type": "text", "text": "Kenya said…"},
          {"type": "final", "answer": {"markdown": "Kenya said…", "citations_total": 1}, "usage": None,
           "briefing_id": "first111"}]


def test_briefings_are_saved_shared_and_withdrawn(db, clock):
    """Where Countries Stand's test, without the web server."""
    archive = url_ids(db, clock)
    question = "What has been said about climate finance since 2020?"
    saved = archive.save(question, {"mode": "summary", "recency": 0.5}, EVENTS, id="first111")
    assert saved == SavedBriefing("first111", "2026-11-13T12:00:00+00:00", question,
                                  {"mode": "summary", "recency": 0.5}, EVENTS)
    got = archive.get("first111")
    assert got == saved and got.events[-1]["type"] == "final" and got.events[-1]["briefing_id"] == "first111"
    assert got.events[-1]["usage"] is None and got.extra == {} and got.withdrawn_at is None
    assert archive.get("nosuchbriefing") is None and archive.get("nope99") is None
    assert archive.withdrawn() == [] and not archive.withdraw("nope99", "No such briefing.")
    clock.advance(hours=1)
    assert archive.withdraw("first111", "It misread a statement.")
    gone = archive.get("first111")
    assert gone.withdrawn_at == "2026-11-13T13:00:00+00:00" and gone.withdrawn_reason == "It misread a statement."
    assert gone.events == EVENTS                                          # the record is kept, not deleted
    assert archive.withdrawn() == [BriefingListing("first111", "2026-11-13T12:00:00+00:00", question,
                                                   "2026-11-13T13:00:00+00:00", "It misread a statement.")]


def test_the_events_are_stored_exactly_as_given(db, clock):
    archive = url_ids(db, clock)
    events = [{"type": "final", "answer": {"segments": [{"text": "x", "flag": None}]}, "prepared": date(2026, 11, 13),
               "something_new": {"kept": True}}]
    archive.save("Q?", {"mode": "summary"}, events, id="abc12345", extra={"records_up_to": date(2026, 11, 12)})
    with db.connect() as con:
        row = con.execute("SELECT options, events, extra FROM wts_briefings").fetchone()
    assert row["events"] == json.dumps(events, default=str)               # as every site writes them today
    assert row["options"] == json.dumps({"mode": "summary"}) and row["extra"] == '{"records_up_to": "2026-11-12"}'


def test_a_briefing_whose_id_is_taken_is_kept_under_another(db, clock):
    """Where Countries Stand's test: a clash of ids once lost a briefing that had been written and paid for. It is
    kept under a new id, which the saved copy carries (and so the reader and the cached copy)."""
    archive = url_ids(db, clock, ids=["fresh222"])
    archive.save("What has been said about climate finance since 2020?", {}, EVENTS, id="first111")
    other = [EVENTS[0], {"type": "final", "answer": {"markdown": "Kenya."}, "briefing_id": "first111"}]
    second = archive.save("What has Kenya said about climate finance?", {}, other, id="first111")
    assert second.id == "fresh222" and second.events[-1]["briefing_id"] == "fresh222"
    assert other[-1]["briefing_id"] == "first111"                         # the caller's own events are not changed
    assert archive.get("fresh222").events[-1]["briefing_id"] == "fresh222"
    assert archive.get("fresh222").question == "What has Kenya said about climate finance?"
    first = archive.get("first111")                                       # the first is untouched
    assert first.question.endswith("since 2020?") and first.events == EVENTS
    assert [b.id for b in archive.recent()] == ["fresh222", "first111"]  # the newest saved first


def test_of_briefings_saved_in_the_same_second_the_one_saved_last_is_listed_first(db, clock):
    """Found by Where MPs Stand's fixes: the list ordered ties by id, which is chance, where the site's own list
    put the newest saved first; the site read the table with its own SQL to keep that."""
    archive = url_ids(db, clock, ids=["mmm", "aaa", "zzz", "bbb"])
    for n in range(3):
        archive.save(f"Question {n}?", {}, EVENTS)  # all in one second, their ids in no order
    clock.advance(1)
    archive.save("A later question?", {}, EVENTS)
    assert [b.id for b in archive.recent()] == ["bbb", "zzz", "aaa", "mmm"]
    assert [b.id for b in archive.recent(2)] == ["bbb", "zzz"]
    db.compact()  # the nightly rewrite of the file keeps that order
    assert [b.id for b in archive.recent()] == ["bbb", "zzz", "aaa", "mmm"]


def test_a_briefing_id_already_in_use_is_tried_again_five_times_in_all(db, clock):
    """Where Councils Stand's test: another id is tried, rather than the reader getting an error after the briefing
    was paid for; five clashes in a row are a fault, and the briefing could not be written."""
    archive = url_ids(db, clock, ids=["taken111", "taken111", "fresh222"])
    archive.save("An earlier question?", {}, [{"type": "final", "answer": None}], id="taken111")
    saved = archive.save("What have councils decided about bin collections?", {}, [{"type": "final", "answer": {}}])
    assert saved.id == "fresh222" and archive.get("taken111").question == "An earlier question?"
    assert archive.get("fresh222").question.startswith("What have councils")
    stuck = BriefingArchive(db, new_id=lambda: "taken111", clock=clock)
    tried: list[str] = []
    counting = BriefingArchive(db, new_id=lambda: tried.append("x") or "taken111", clock=clock)
    with pytest.raises(RuntimeError, match="could not allocate a briefing id"):
        stuck.save("What have councils decided about public toilets?", {}, [])
    with pytest.raises(RuntimeError):
        counting.save("What have councils decided about public toilets?", {}, [])
    assert len(tried) == 5 + 1                                            # five tried; the sixth is never used
    assert len(archive.recent()) == 2


def test_a_site_without_an_id_of_its_own_in_the_events_gets_one_made(db, clock):
    """Where MPs Stand's way: ten characters that can be read aloud, made when the briefing is kept; what only it
    keeps (the date of the newest record, the model) goes in ``extra``."""
    archive = BriefingArchive(db, new_id=lambda: alphabet_id(MPS_ALPHABET, 10), clock=clock)
    events = [{"type": "plan", "plan": {}}, {"type": "sources", "sources": []},
              {"type": "final", "answer": {"citations_total": 1}, "model": "claude-sonnet-5-5"}]
    saved = archive.save("What has been said about trial by jury?", {"mode": "summary", "scope": {"votes": True}},
                         events, extra={"records_up_to": "2026-11-12", "model": "claude-sonnet-5-5"})
    assert len(saved.id) == 10 and MPS_ID.match(saved.id) and saved.created_at == "2026-11-13T12:00:00+00:00"
    got = archive.get(saved.id)
    assert got.options == {"mode": "summary", "scope": {"votes": True}} and got.events == events
    assert got.extra == {"records_up_to": "2026-11-12", "model": "claude-sonnet-5-5"}
    assert "usage" not in json.dumps(got.events)
    assert archive.get("abcdefghij") is None and archive.get("ZZZ'<script>") is None
    # the owner's list: newest first, with what was withdrawn and why
    clock.advance(60)
    later = archive.save("A later question?", {}, events)
    archive.withdraw(saved.id, "complaint")
    listed = archive.recent(limit=50)
    assert [b.id for b in listed] == [later.id, saved.id] and listed[1].withdrawn_reason == "complaint"
    assert archive.recent(limit=1) == listed[:1] and [b.id for b in archive.withdrawn()] == [saved.id]


def test_ids_are_made_the_sites_two_ways():
    assert token_id(8, random=FixedRandom(tokens=["SAMEid11"])) == "SAMEid11"
    assert len(token_id(8)) == 11 and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", token_id(8))   # 64 bits, as the two sites'
    assert alphabet_id(MPS_ALPHABET, 10, random=FixedRandom(choices=[0, 31, 2])) == "a9caaaaaaa"
    made = {alphabet_id(MPS_ALPHABET, 10) for _ in range(50)}
    assert len(made) == 50 and all(MPS_ID.match(i) for i in made)
    assert len(BriefingArchive.__init__.__kwdefaults__ or {}) == 1        # only the clock: no id format is assumed


def test_withdrawn_briefings_are_listed_most_recent_first(db, clock):
    archive = url_ids(db, clock)
    for bid in ("one11111", "two22222", "three333"):
        archive.save(f"Question {bid}?", {}, [], id=bid)
        clock.advance(60)
    archive.withdraw("two22222", "It named the wrong council.")
    clock.advance(60)
    archive.withdraw("one11111", "")
    assert [(b.id, b.withdrawn_reason) for b in archive.withdrawn()] == [
        ("one11111", ""), ("two22222", "It named the wrong council.")]
    clock.advance(60)
    archive.withdraw("two22222", "Withdrawn again, for another reason.")   # the latest reason is the one shown
    assert [b.id for b in archive.withdrawn()] == ["two22222", "one11111"]
    assert archive.get("three333").withdrawn_at is None


# Notes of failures


def test_failures_are_kept_for_90_days(db, clock):
    """Where Countries Stand's test: its privacy notice says these are deleted after 90 days."""
    failures = Failures(db, clock=clock)
    with db.connect() as con:
        con.execute("INSERT INTO wts_failures (at, kind, question, error) VALUES ('2020-01-01T00:00:00+00:00', 'x', "
                    "'old', 'e')")
    failures.note("briefing", "new", "e")
    assert [f["question"] for f in failures.recent()] == ["new"]
    clock.advance(days=90)
    failures.note("briefing", "ninety days on", "e")                     # exactly 90 days old is still kept
    assert [f["question"] for f in failures.recent()] == ["ninety days on", "new"]
    clock.advance(1)
    failures.note("briefing", "a second later", "e")
    assert [f["question"] for f in failures.recent()] == ["a second later", "ninety days on"]


def test_only_the_newest_500_failures_are_kept(db, clock):
    failures = Failures(db, clock=clock)
    for n in range(503):
        failures.note("briefing", f"q{n}", "e")
    kept = failures.recent(None)
    assert len(kept) == 500 and kept[0]["question"] == "q502" and kept[-1]["question"] == "q3"
    assert len(failures.recent()) == 20 and [f["question"] for f in failures.recent(2)] == ["q502", "q501"]


def test_a_failure_is_noted_with_its_kind_and_cut_to_500_characters(db, clock):
    """Where MPs Stand's test of its alerts: one failure, its kind and its error."""
    failures = Failures(db, clock=clock)
    assert failures.recent() == []
    failures.note("question reading", "Q?", "AuthenticationError: invalid x-api-key")
    assert failures.recent() == [{"at": "2026-11-13T12:00:00+00:00", "kind": "question reading", "question": "Q?",
                                  "error": "AuthenticationError: invalid x-api-key"}]
    clock.advance(hours=25)
    failures.note("briefing", "q" * 600, "RuntimeError: " + "x" * 600)
    failures.note("topic", None, "e")
    newest = failures.recent()
    assert [f["kind"] for f in newest] == ["topic", "briefing", "question reading"]
    assert newest[0]["question"] == "" and len(newest[1]["question"]) == 500 and len(newest[1]["error"]) == 500
    assert newest[1]["error"].startswith("RuntimeError")
    # the last 24 hours, for an alert: how many, and the latest
    day_ago = "2026-11-13T13:00:00+00:00"
    assert [f["kind"] for f in failures.recent(None, since=day_ago)] == ["topic", "briefing"]
    assert failures.recent(1, since=day_ago)[0]["kind"] == "topic"


def test_a_new_id_never_begins_with_a_dash_and_is_otherwise_as_it_was():
    """Found by running Where Councils Stand's own tests against 0.3.0, and confirmed by its second review: one
    id in 64 began with "-", which a command line reads as an option, so `withdraw -vPeHLp1u54` ended "no such
    option" (and the site's test of it failed about one run in twelve). Such an id is drawn again."""
    import secrets

    from wts_core.ports import SYSTEM_RANDOM

    chance = FixedRandom(tokens=["-vPeHLp1u54", "-_another11", "aB-_9zQx7Yk"])
    assert token_id(8, random=chance) == "aB-_9zQx7Yk"  # the two that begin with a dash are passed over
    assert token_id(8, random=FixedRandom(tokens=["_vPeHLp1u54"])) == "_vPeHLp1u54"  # only a dash, and only first
    made = [token_id(8) for _ in range(4000)]
    assert not [m for m in made if m.startswith("-")] and any("-" in m[1:] for m in made)
    assert {len(m) for m in made} == {11} and all(re.fullmatch(r"[A-Za-z0-9_-]{11}", m) for m in made)
    assert len({m[0] for m in made}) > 50  # every other first character still turns up
    # an id made before, dash and all, is still an id: nothing about reading one has changed
    assert len(secrets.token_urlsafe(8)) == len(SYSTEM_RANDOM.token(8)) == 11

    class OnlyDashes:
        def token(self, nbytes: int) -> str:
            return "-" * 11

    with pytest.raises(RuntimeError, match="no id could be made"):
        token_id(8, random=OnlyDashes())
