"""Test questions proposed from real use (wts_core.observe.propose, and the ``propose-questions`` command): what is
proposed, what never is, and that nothing joins a test set without a person.

Each question that must not be proposed carries a marker found nowhere else, and the file is searched for it.
"""

from __future__ import annotations

import stat
import tomllib
from datetime import timedelta
from pathlib import Path

import pytest

from cli_sites import mounted, run
from test_observe_log import SITE, record
from wts_core import observe
from wts_core.cli import StatsNames, stats_commands
from wts_core.eval import load_cases
from wts_core.observe import REASONS, Proposed, SqliteBriefingLog, proposals_toml, proposed_questions
from wts_core.state import StateDB
from wts_core.testing import FixedClock

NOW = "2026-11-13T12:00:00+00:00"
DAY = "2026-11-12T10:00:00+00:00"

# questions that may be proposed
NO_RECORDS = "What did the council decide about the heliport?"
NOT_USEFUL = "What has been said about library opening hours?"
WORST = "How did members vote on the waste contract?"
# questions that must never be: each has a marker of its own
FAILED_LONG_AGO = "MARKER-FAILED-LONG-AGO what was said about the flood wall?"
FAILED_THIS_WEEK = "MARKER-FAILED-THIS-WEEK what broke?"
SOURCES_ONLY = "MARKER-SOURCES-ONLY what are the sources on parking?"
PAUSED = "MARKER-PAUSED a question a cap stopped"
LEFT = "MARKER-LEFT a question the reader left"
WITHDRAWN = "MARKER-WITHDRAWN a question whose briefing was since withdrawn"
NOT_SAVED = "MARKER-NOT-SAVED a briefing that was written and is at no address"
THE_CHECKS = "MARKER-NIGHTLY the nightly check's own question"
FINE = "MARKER-FINE a question whose briefing was well checked and found useful"
REPORTED = "MARKER-REPORTED a question whose briefing a reader has reported"
HIDDEN = "MARKER-HIDDEN a question whose briefing is hidden while a concern about it is decided"
NEVER = (FAILED_LONG_AGO, FAILED_THIS_WEEK, SOURCES_ONLY, PAUSED, LEFT, WITHDRAWN, NOT_SAVED, THE_CHECKS, FINE,
         REPORTED, HIDDEN)


def NOTHING_HIDDEN(briefing: str) -> bool:  # noqa: N802  # a site on which nothing can be hidden says so
    return False


def HIDDEN_NOW(briefing: str) -> bool:  # noqa: N802  # as a site answers from its right of reply: replies.hidden(…)
    return briefing == "saved-h1"


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def db(tmp_path, clock) -> StateDB:
    return StateDB(tmp_path / "data" / "state.db", migrations=observe.migrations(), clock=clock)


@pytest.fixture
def log(db, clock) -> SqliteBriefingLog:
    """A week of the record, with every kind of row a question could come from. The rows that must not be
    proposed hold their questions here even where the desk would have written none: the rule must not rest on a
    row's question happening to be empty."""
    log = SqliteBriefingLog(db, clock=clock)
    checked = dict(citations_invalid=0, unsupported=0, quotes_unverified=0, loaded_words=0)
    for row in (
        record("n1", DAY, "no_records", question=NO_RECORDS),
        record("n2", "2026-11-12T11:00:00+00:00", "no_records", question=NO_RECORDS.upper()),  # the same, asked again
        record("u1", DAY, question=NOT_USEFUL, briefing_id="saved-u1", useful=False, **checked),
        record("w1", DAY, question=WORST, briefing_id="saved-w1", citations_invalid=2, unsupported=1,
               quotes_unverified=0, loaded_words=1),
        record("w2", DAY, question="A briefing with one small flag?", briefing_id="saved-w2", citations_invalid=0,
               unsupported=1, quotes_unverified=0, loaded_words=0),
        # a failed briefing whose 90 days are long past, with its question still there (the tidy has not run)
        record("f1", "2026-07-01T10:00:00+00:00", "error", question=FAILED_LONG_AGO, error_type="RuntimeError"),
        record("f2", DAY, "error", question=FAILED_THIS_WEEK, error_type="RuntimeError"),
        record("s1", DAY, "sources_only", question=SOURCES_ONLY),
        record("p1", DAY, "paused_cap", question=PAUSED),
        record("l1", DAY, "left", question=LEFT),
        record("c1", DAY, question=WITHDRAWN, briefing_id="saved-c1", corrected=True, useful=False,
               citations_invalid=5, unsupported=5, quotes_unverified=5, loaded_words=5),
        record("x1", DAY, question=NOT_SAVED, useful=False, citations_invalid=4, unsupported=0, quotes_unverified=0,
               loaded_words=0),
        record("r1", DAY, question=REPORTED, briefing_id="saved-r1", reported=True, useful=False,
               citations_invalid=5, unsupported=5, quotes_unverified=5, loaded_words=5),
        record("h1", DAY, question=HIDDEN, briefing_id="saved-h1", useful=False, citations_invalid=6, unsupported=5,
               quotes_unverified=5, loaded_words=5),
        record("k1", DAY, "no_records", kind="check", question=THE_CHECKS),
        record("g1", DAY, question=FINE, briefing_id="saved-g1", useful=True, **checked),
    ):
        log.write(row)
    return log


def test_questions_that_found_nothing_were_not_useful_or_were_worst_checked_are_proposed(log, clock):
    found = proposed_questions(log, since=timedelta(days=7), clock=clock, leave_out=HIDDEN_NOW)
    assert found == (
        Proposed(NO_RECORDS, "no-records", times=2),
        Proposed(NOT_USEFUL, "not-useful", briefing_id="saved-u1"),
        Proposed(WORST, "worst-checked", briefing_id="saved-w1", problems=4),
        Proposed("A briefing with one small flag?", "worst-checked", briefing_id="saved-w2", problems=1))
    assert [p.reason for p in found] == sorted((p.reason for p in found), key=REASONS.index)
    assert proposed_questions(log, since=timedelta(days=7), limit=1, clock=clock,
                              leave_out=HIDDEN_NOW)[-1].question == WORST


def test_only_questions_the_record_may_hold_and_of_saved_briefings_not_since_withdrawn_are_ever_proposed(log, clock):
    """Never the question of a failed briefing (least of all one past its 90
    days), of a request for the sources only, of one a cap stopped or the reader left; never one whose briefing
    was withdrawn or corrected, or is at no address; never the nightly check's."""
    for since in (timedelta(days=7), timedelta(days=200)):  # a period that reaches back past the failed one too
        said = proposals_toml(proposed_questions(log, since=since, limit=50, clock=clock, leave_out=HIDDEN_NOW),
                              SITE, since=clock.now() - since, until=clock.now())
        assert "MARKER" not in said, [marker for marker in NEVER if marker.split()[0] in said]
        assert NO_RECORDS in said and NOT_USEFUL in said and WORST in said


def test_a_briefing_hidden_while_a_concern_is_decided_or_reported_by_a_reader_is_never_proposed(log, db, clock, tmp_path):
    """Found by the independent review of 0.3.0: a briefing an open report names, hidden by the owner while the
    concern is decided, had its question copied into the file of proposals. This module may not read the right
    of reply's tables (ADR 0008), so the site says which briefings are hidden; a reported one is left out by the
    record's own mark. And the command will not run until the site has said."""
    week = dict(since=timedelta(days=7), limit=50, clock=clock)
    # the site's function is what keeps a hidden briefing out: without it, it would be proposed
    assert HIDDEN in [p.question for p in proposed_questions(log, **week)]
    assert HIDDEN not in [p.question for p in proposed_questions(log, leave_out=HIDDEN_NOW, **week)]
    # a reported one is out whatever the site says, and comes back only if the mark is taken off
    assert REPORTED not in [p.question for p in proposed_questions(log, leave_out=NOTHING_HIDDEN, **week)]
    asked: list[str] = []
    proposed_questions(log, leave_out=lambda briefing: bool(asked.append(briefing)), **week)
    assert sorted(asked) == ["saved-g1", "saved-h1", "saved-u1", "saved-w1", "saved-w2"]  # saved, unmarked ones only
    # the command: not without being told; and with the site's function, the hidden one is not in the file
    data = tmp_path / "data"
    untold = mounted(stats_commands(SITE, lambda: db, thresholds=dict, folder=lambda: data / "reports", clock=clock))
    refused = run(untold, ["propose-questions"], tmp_path)
    assert refused.exit_code == 1 and "has not said which briefings' questions are never to be proposed" in refused.stderr
    assert not (data / "proposed-questions").exists()
    told = mounted(stats_commands(SITE, lambda: db, thresholds=dict, folder=lambda: data / "reports", clock=clock,
                                  proposals_leave_out=HIDDEN_NOW))
    assert run(told, ["propose-questions"], tmp_path).exit_code == 0
    (made,) = (data / "proposed-questions").iterdir()
    assert "MARKER" not in made.read_text() and NOT_USEFUL in made.read_text()


def test_a_question_is_proposed_once_under_the_first_reason_it_has(db, clock):
    log = SqliteBriefingLog(db, clock=clock)
    log.write(record("b1", DAY, question="Why was the meeting moved?", briefing_id="saved-b1", useful=False,
                     citations_invalid=3, unsupported=0, quotes_unverified=0, loaded_words=0))
    assert proposed_questions(log, since=timedelta(days=7), clock=clock) == (
        Proposed("Why was the meeting moved?", "not-useful", briefing_id="saved-b1", problems=3),)


def test_what_looks_personal_is_taken_out_and_the_owner_is_told_a_name_cannot_be(db, clock):
    log = SqliteBriefingLog(db, clock=clock)
    log.write(record("p1", DAY, "no_records", question="Why has jo.bloggs@example.org of 14 Acacia Avenue (call "
                                                         "+44 20 7946 0958) heard nothing? See https://example.org/x"))
    [found] = proposed_questions(log, since=timedelta(days=7), clock=clock)
    assert found.question == ("Why has [removed] of 14 Acacia Avenue (call [removed]) heard nothing? See [removed]")
    said = proposals_toml([found], SITE, since=clock.now() - timedelta(days=7), until=clock.now())
    assert "jo.bloggs" not in said and "7946" not in said
    assert "a name can only be spotted by a person" in said


def test_the_fragment_is_in_the_shape_of_a_sites_questions_file_and_says_it_is_not_one(log, clock, tmp_path):
    found = proposed_questions(log, since=timedelta(days=7), clock=clock, leave_out=HIDDEN_NOW)
    said = proposals_toml(found, SITE, since=clock.now() - timedelta(days=7), until=clock.now())
    assert said.startswith("# Proposed test questions for Where Councils Stand, from readers' questions between "
                           "6 November 2026 and 13 November 2026.")
    assert "NOTHING HERE IS IN THE TEST SET" in said
    tables = tomllib.loads(said)["q"]
    assert [t["id"] for t in tables] == [f"proposed-2026-11-13-{n:02d}" for n in (1, 2, 3, 4)]
    assert [t["category"] for t in tables] == ["proposed-no-records", "proposed-not-useful", "proposed-worst-checked",
                                               "proposed-worst-checked"]
    assert set(tables[0]) == {"id", "question", "category"}  # what to expect of each is the owner's to say
    assert "# Proposed because it found no records; asked 2 times." in said
    assert "# Proposed because the checks found 4 problems in its briefing; saved as saved-w1." in said
    path = tmp_path / "proposed.toml"
    path.write_text(said)
    assert [c.question for c in load_cases(path)] == [p.question for p in found]  # the harness's own reader takes it
    # a question with quotes, a backslash and a line break is still one line of valid TOML
    odd = 'Did the leader say "no cuts" \\ or\nnot?'
    again = tomllib.loads(proposals_toml([Proposed(odd, "no-records")], SITE, since=clock.now() - timedelta(days=1),
                                         until=clock.now()))
    assert again["q"][0]["question"] == odd
    nothing = proposals_toml([], SITE, since=clock.now() - timedelta(days=1), until=clock.now())
    assert "No question of this period is proposed" in nothing and tomllib.loads(nothing) == {}


def test_the_command_writes_one_file_under_the_data_folder_prints_its_path_and_adds_nothing_to_the_test_set(
        log, db, clock, tmp_path):
    data = tmp_path / "data"
    eval_folder = tmp_path / "eval"
    eval_folder.mkdir()
    questions = eval_folder / "questions.toml"
    questions.write_text('today = 2026-10-11\n\n[[q]]\nid = "bins"\nquestion = "What about bins?"\ncategory = "x"\n')
    before = questions.read_bytes()
    app = mounted(stats_commands(SITE, lambda: db, thresholds=dict, folder=lambda: data / "reports", clock=clock,
                                 proposals_leave_out=HIDDEN_NOW))
    said = run(app, ["propose-questions"], tmp_path)
    path = data / "proposed-questions" / "2026-11-13-from-2026-11-06.toml"
    assert said.exit_code == 0 and said.stdout.splitlines() == [
        "<root>/data/proposed-questions/2026-11-13-from-2026-11-06.toml", "4 questions proposed. Nothing has been added to the test set: read the file, and copy what you "
                   "approve into eval/questions.toml by hand."]
    text = path.read_text()
    assert "MARKER" not in text and NO_RECORDS in text and len(tomllib.loads(text)["q"]) == 4
    assert stat.S_IMODE(path.stat().st_mode) == 0o600  # it quotes readers' questions: for the owner only
    # nothing else was written anywhere: the test set is as it was, and the only new file is the one printed
    assert questions.read_bytes() == before and sorted(p.name for p in eval_folder.iterdir()) == ["questions.toml"]
    made = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file() and "state.db" not in p.name)
    assert made == ["data/proposed-questions/2026-11-13-from-2026-11-06.toml", "eval/questions.toml"]
    # a period, a limit and another folder may be given; a period that is none is refused
    fewer = run(app, ["propose-questions", "--since", "2026-11-12", "--limit", "1", "--to", str(tmp_path / "out")],
                tmp_path)
    assert fewer.exit_code == 0 and fewer.stdout.startswith("<root>/out/2026-11-13-from-2026-11-12.toml")
    assert (tmp_path / "out" / "2026-11-13-from-2026-11-12.toml").exists()
    assert "3 questions proposed." in fewer.stdout
    assert run(app, ["propose-questions", "--since", "soon"], tmp_path).exit_code == 1


def test_a_file_of_proposals_does_not_outlive_the_record_it_came_from(log, db, clock, tmp_path):
    """It quotes questions, so the nightly tidy deletes it when it is older than a row of the record is kept."""
    data = tmp_path / "data"
    app = mounted(stats_commands(SITE, lambda: db, thresholds=dict, folder=lambda: data / "reports", clock=clock,
                                 proposals_leave_out=HIDDEN_NOW))
    assert run(app, ["propose-questions"], tmp_path).exit_code == 0
    path = data / "proposed-questions" / "2026-11-13-from-2026-11-06.toml"
    (path.parent / "notes.toml").write_text("# the owner's own notes\n")
    # A file is kept by the oldest question it could hold: the first day of its period, a week before it was made.
    # The review found one made for a year back kept a question about 25 months, where the record keeps it 13.
    assert run(app, ["propose-questions", "--since", "365d"], tmp_path).exit_code == 0
    a_year_back = data / "proposed-questions" / "2026-11-13-from-2025-11-13.toml"
    assert a_year_back.exists() and NO_RECORDS in a_year_back.read_text()
    assert "proposed test questions" not in run(app, ["tidy"], tmp_path).stdout  # nothing is thirteen months old yet
    clock.advance(days=31)  # the year-back file's first day is now more than thirteen months gone
    said = run(app, ["tidy"], tmp_path).stdout
    assert "Deleted 1 file of proposed test questions that could hold a question older than 13 months." in said
    assert not a_year_back.exists() and path.exists()
    clock.advance(days=394 - 31 - 7)  # the week's file: a day short of thirteen months from its first day
    assert "proposed test questions" not in run(app, ["tidy"], tmp_path).stdout and path.exists()
    clock.advance(days=5)
    assert "Deleted 1 file of proposed test questions that could hold" in run(app, ["tidy"], tmp_path).stdout
    assert not path.exists() and (path.parent / "notes.toml").exists()
    # a file named for its day alone (as a first draft of this command named them) goes by that day
    old_name = path.parent / "2025-01-01.toml"
    old_name.write_text("# proposals\n")
    assert "Deleted 1 file" in run(app, ["tidy"], tmp_path).stdout and not old_name.exists()


def test_a_site_may_rename_the_command_or_leave_it_out(db, clock, tmp_path):
    def app(**names: str | None):
        return mounted(stats_commands(SITE, lambda: db, thresholds=dict, folder=lambda: tmp_path / "reports",
                                      names=StatsNames(**names), clock=clock, proposals_leave_out=HIDDEN_NOW))

    assert run(app(propose="suggest-test-questions"), ["suggest-test-questions"], tmp_path).exit_code == 0
    assert run(app(propose=None), ["propose-questions"], tmp_path).exit_code == 2


def test_a_period_must_say_its_timezone_and_run_forwards(db, clock):
    from datetime import datetime

    log = SqliteBriefingLog(db, clock=clock)
    with pytest.raises(ValueError, match="timezone"):
        proposed_questions(log, since=datetime(2026, 11, 1), clock=clock)
    with pytest.raises(ValueError, match="begin before it ends"):
        proposed_questions(log, since=clock.now() + timedelta(days=1), clock=clock)
    with pytest.raises(ValueError, match="at least 1"):
        proposed_questions(log, since=timedelta(days=1), limit=0, clock=clock)
    assert Path
