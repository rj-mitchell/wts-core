"""Reading the sites' test questions and judgements as they stand: wts_core.eval.cases.

The files are each site's own, read from its checkout (beside this repository, or under ``WTS_SITES_DIR``); a test
whose checkout is absent is skipped with the reason.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from adapters_sites import sites_dir
from wts_core.eval import Case, Judgement, load_cases, load_judgements, read_as_if


def theirs(repo: str, name: str) -> Path:
    home = sites_dir()
    path = home / repo / "eval" / name if home else None
    if path is None or not path.is_file():
        pytest.skip(f"no eval/{name} in a checkout of {repo} beside this repository or under WTS_SITES_DIR")
    return path


def by_id(cases: list[Case]) -> dict[str, Case]:
    return {c.id: c for c in cases}


def test_where_mps_stands_questions_are_read_as_they_stand():
    path = theirs("wherempsstand", "questions.toml")
    cases = load_cases(path)
    assert len(cases) == 66
    assert read_as_if(path) == date(2026, 10, 11)
    assert cases[0].id == "wind"  # the file's order is kept
    wind = by_id(cases)["wind"]
    assert wind.question == "Where do rural and city MPs differ on onshore wind?"
    assert dict(wind.expect) == {"houses_any": [[], ["commons"]], "portfolios": ["energy_climate"],
                                 "category": "topic"}
    # a follow-up question keeps the questions before it
    follow = by_id(cases)["follow-lords"]
    assert follow.expect["history"] == ["What have MPs said about the assisted dying bill?"]
    assert follow.expect["houses"] == ["lords"]
    assert Counter(c.expect["category"] for c in cases)["demographic"] == 14


def test_where_countries_stands_questions_are_read_as_they_stand():
    path = theirs("wherecountriesstand", "questions.toml")
    cases = load_cases(path)
    assert len(cases) == 55
    assert read_as_if(path) == date(2026, 10, 25)
    grain = by_id(cases)["ukraine-grain"]
    assert grain.question == "What has Ukraine said about the Black Sea Grain Initiative?"
    # what stands beside the expect table (the category, the countries the evidence must include) is kept with it
    assert dict(grain.expect) == {"countries": ["UKR"], "date_from": "default", "category": "country",
                                  "include": ["UKR"]}
    tuvalu = by_id(cases)["none-tuvalu-1995"]
    assert tuvalu.expect["no_records"] is True and tuvalu.expect["sources"] == ["sc"]
    assert sum(1 for c in cases if c.expect.get("no_records")) == 6
    assert sum(1 for c in cases if c.expect.get("include")) == 12
    assert sum(1 for c in cases if "note" in c.expect) == 1


def test_where_councils_stands_questions_are_read_as_they_stand():
    path = theirs("wherecouncilsstand", "questions.toml")
    cases = load_cases(path)
    assert len(cases) == 31
    assert read_as_if(path) == date(2026, 11, 6)
    assert dict(by_id(cases)["bins-weekly"].expect) == {"date_from": "default", "category": "topic"}
    before = by_id(cases)["before-records"]
    assert before.question == "What did councils decide about bin collections in 2012?"
    assert dict(before.expect) == {"date_from": "2012", "date_to": "2012", "category": "dates", "no_records": True}
    assert sum(1 for c in cases if c.expect.get("include")) == 5


def test_where_mps_stands_judgements_are_read_as_they_stand():
    judgements = load_judgements(theirs("wherempsstand", "judgments.jsonl"))
    assert len(judgements) == 2649
    assert judgements[0] == Judgement("wind", "uk.org.publicwhip/wrans/2026-05-20.3564.r0", 1, judgements[0].judge)
    assert Counter(j.grade for j in judgements) == {2: 1748, 1: 825, 0: 76}
    assert len({j.id for j in judgements}) == 62
    assert len({j.judge for j in judgements}) == 1 and judgements[0].judge
    # the site's own reader: one grade for each source of each question
    assert len({(j.id, j.record_id): j.grade for j in judgements}) == 2649


# ---- without a checkout ----------------------------------------------------------------------------------------


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "questions.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_questions_file_of_any_sites_shape_is_read(tmp_path):
    path = write(tmp_path, '''
today = "2026-11-06"

[[q]]
id = "a"
question = "What was decided about bins?"
category = "topic"
expect = { date_from = "default", kinds_any = [[], ["cabinet"]] }
include = ["E06000001"]

[[q]]
id = "b"
question = "And in 2012?"
history = ["What was decided about bins?"]
no_records = true
''')
    a, b = load_cases(path)
    assert a == Case("a", "What was decided about bins?", a.expect)
    assert dict(a.expect) == {"date_from": "default", "kinds_any": [[], ["cabinet"]], "category": "topic",
                              "include": ["E06000001"]}
    assert dict(b.expect) == {"history": ["What was decided about bins?"], "no_records": True}  # no expect table
    assert read_as_if(path) == date(2026, 11, 6)
    with pytest.raises(TypeError):
        a.expect["category"] = "changed"  # type: ignore[index]  # what a site expects is not to be altered


def test_a_file_with_no_date_has_none(tmp_path):
    assert read_as_if(write(tmp_path, '[[q]]\nid = "a"\nquestion = "Why?"\n')) is None


@pytest.mark.parametrize(("text", "says"), [
    ('today = "2026-11-06"\n', "has no questions"),
    ('[[q]]\nid = "a"\n', "question 1 needs an id and a question"),
    ('[[q]]\nid = "a"\nquestion = "Why?"\n[[q]]\nid = "a"\nquestion = "How?"\n', "ids must be unique"),
    ('[[q]]\nid = "a"\nquestion = "Why?"\ncategory = "x"\nexpect = { category = "y" }\n', "both inside expect"),
    ('[[q]]\nid = "a"\nquestion = "Why?"\nexpect = "none"\n', "expect must be a table"),
    ("[[q]\n", "is not valid TOML"),
])
def test_a_questions_file_that_cannot_be_read_is_refused_by_name(tmp_path, text, says):
    path = write(tmp_path, text)
    with pytest.raises(ValueError, match=says) as raised:
        load_cases(path)
    assert str(path) in str(raised.value)


def test_a_date_that_is_no_date_is_refused(tmp_path):
    with pytest.raises(ValueError, match="today must be a date"):
        read_as_if(write(tmp_path, 'today = "last Tuesday"\n'))


def test_judgements_are_read_in_order_and_a_missing_file_is_none_yet(tmp_path):
    assert load_judgements(tmp_path / "judgments.jsonl") == []
    path = tmp_path / "judgments.jsonl"
    path.write_text('{"id": "wind", "record_id": "r1", "grade": 2, "judge": "a-model"}\n\n'
                    '{"id": "wind", "record_id": "r1", "grade": 0}\n', encoding="utf-8")
    assert load_judgements(path) == [Judgement("wind", "r1", 2, "a-model"), Judgement("wind", "r1", 0, "")]
    # the site's own reader keeps the later grade
    assert {(j.id, j.record_id): j.grade for j in load_judgements(path)} == {("wind", "r1"): 0}


def test_a_line_that_is_no_judgement_is_named(tmp_path):
    path = tmp_path / "judgments.jsonl"
    path.write_text('{"id": "wind", "record_id": "r1", "grade": 2}\n{"id": "wind"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2: not a judgement"):
        load_judgements(path)
