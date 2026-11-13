"""Replay: the checks run again over recorded briefings, and every difference named: wts_core.eval.replay.

The recordings that ship with the package (``wts_core.testing.recorded``) are replayed with each site's own inputs
against reports recorded once under ``tests/golden/eval/<site>/``. A change to the verifier, a word list or the
spelling rules that alters any of them fails here, and says what changed; to accept a change that is meant, run
the tests once with ``WTS_UPDATE_GOLDEN=1`` and read the difference in the golden files before committing them.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from checks_sites import COUNCILS, COUNTRIES, MPS, SITES, SiteChecks, src
from eval_briefings import BLOCKS, CLAIM, DOCUMENTS, HEADINGS, NOTE, QUESTION, fixture
from wts_core.checks import COMMON_LOADED_WORDS, EVIDENCE_NOTES_STRICT, LoadedWords, Verifier
from wts_core.eval import (
    Difference,
    Fixture,
    assert_never_weaker,
    checked,
    load_fixture,
    replay,
    save_fixture,
)
from wts_core.events import Block, Citation, Completed, blocks_as_today
from wts_core.ports import Document, Usage
from wts_core.testing.models import ScriptedModel, load_header, record_stream, recorded

GOLDEN = Path(__file__).parent / "golden" / "eval"
RECORDED = ("cited_briefing", "max_tokens", "real_cited_briefing", "real_nothing_relevant", "refusal",
            "uncited_claim")


def report(f: Fixture, site: SiteChecks, **changed: Any) -> Fixture:
    """The fixture with the report one site's checks make of it today."""
    made = checked(f.blocks, f.documents, site.verifier, site.loaded_words, headings=f.headings, curled=site.curled)
    return replace(f, report=made, **changed)


def again(f: Fixture, site: SiteChecks, verifier: Verifier | None = None,
          loaded: LoadedWords | None = None) -> list[Difference]:
    return replay([f], verifier or site.verifier, loaded or site.loaded_words, curled=site.curled)


def said(differences: list[Difference]) -> set[tuple[str, str | None, Any, Any, str]]:
    return {(d.check, d.sentence, d.before if not isinstance(d.before, list) else tuple(d.before),
             d.after if not isinstance(d.after, list) else tuple(d.after), d.kind) for d in differences}


# ---- the recordings that ship with the package -----------------------------------------------------------------


@pytest.mark.parametrize("name", RECORDED)
@pytest.mark.parametrize("site", SITES, ids=lambda s: s.name)
def test_the_checks_say_today_what_they_said_of_each_shipped_recording(site, name):
    golden = GOLDEN / site.name / f"{name}.report.json"
    if os.environ.get("WTS_UPDATE_GOLDEN"):
        made = report(load_fixture(recorded(name)), site).report
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(json.dumps(made, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    differences = again(load_fixture(recorded(name), report=golden), site)
    assert differences == [], "\n".join(str(d) for d in differences)
    assert_never_weaker(differences)


def test_every_shipped_stream_has_a_golden_report():
    shipped = {p.stem for p in recorded("cited_briefing").parent.glob("*.jsonl")}
    assert shipped == set(RECORDED), "a recording was added or removed: add it to RECORDED and record its reports"
    for site in SITES:
        assert {p.name for p in (GOLDEN / site.name).glob("*.json")} == {f"{n}.report.json" for n in RECORDED}


def test_the_golden_reports_hold_what_the_recordings_were_made_to_show():
    def golden(name: str) -> dict[str, Any]:
        return json.loads((GOLDEN / "councils" / f"{name}.report.json").read_text(encoding="utf-8"))

    assert golden("real_cited_briefing")["citations_total"] == 5
    assert golden("real_cited_briefing")["grounded_ratio"] == 1.0
    claim = golden("uncited_claim")
    assert claim["unsupported_segments"] == 1 and claim["grounded_ratio"] == 0.557
    assert [s["text"] for s in claim["segments"] if s["status"] == "unsupported"] == [
        " This makes Northbridge the first council in the county to do so.\n"]
    assert golden("refusal")["segments"] == []


# ---- a checked report is made as a site's pipeline makes it ----------------------------------------------------


@pytest.mark.parametrize("site", SITES, ids=lambda s: s.name)
def test_a_checked_report_is_what_the_sites_pipeline_order_gives(site):
    sources = [src(d.number, *d.passages, title=d.title, heading=HEADINGS[i]) for i, d in enumerate(DOCUMENTS)]
    theirs = site.check(blocks_as_today(Completed(BLOCKS, "", None, Usage())), sources)
    assert checked(BLOCKS, DOCUMENTS, site.verifier, site.loaded_words, headings=HEADINGS, curled=site.curled) == theirs


def test_the_made_up_briefing_meets_every_check():
    answer = report(fixture(), COUNCILS).report
    assert answer is not None
    counts = {k: v for k, v in answer.items() if k not in ("segments", "markdown")}
    assert counts == {"no_records": False, "citations_total": 3, "citations_invalid": 1, "grounded_ratio": 0.36,
                      "unsupported_segments": 2, "loaded_words": 1, "quotes_total": 3, "quotes_unverified": 1,
                      "rules": 1}
    text = "".join(s["text"] for s in answer["segments"])
    assert text.startswith("Two councils took different courses.")  # the opener about the records is dropped
    assert "favoured a new programme" in text  # the model's own words are made British
    assert [s["status"] for s in answer["segments"]] == [
        "connective", "connective", "cited", "unsupported", "connective", "cited", "invalid", "connective",
        "unsupported"]


def test_a_quotation_from_a_heading_is_found_only_when_the_headings_are_kept():
    with_headings = checked(BLOCKS, DOCUMENTS, MPS.verifier, MPS.loaded_words, headings=HEADINGS)
    without = checked(BLOCKS, DOCUMENTS, MPS.verifier, MPS.loaded_words)
    assert (with_headings["quotes_unverified"], without["quotes_unverified"]) == (1, 2)
    with pytest.raises(ValueError, match="1 headings for 2 documents"):
        checked(BLOCKS, DOCUMENTS, MPS.verifier, MPS.loaded_words, headings=HEADINGS[:1])


def test_a_site_with_curly_quotes_gets_its_report_curled():
    answer = report(fixture(), COUNTRIES).report
    assert answer is not None and "“a poor use of public money”" in answer["markdown"]
    assert again(report(fixture(), COUNTRIES), COUNTRIES) == []


# ---- what replay says of a change ------------------------------------------------------------------------------


@pytest.mark.parametrize("site", SITES, ids=lambda s: s.name)
def test_nothing_changed_is_no_difference(site):
    assert again(report(fixture(), site), site) == []


def test_a_weakened_verifier_is_reported_as_weaker_and_fails_ci():
    """A pattern for notes about the evidence that excuses a claim: the sentence it clears is named."""
    f = load_fixture(recorded("uncited_claim"), report=GOLDEN / "councils" / "uncited_claim.report.json")
    excusing = Verifier(no_records=COUNCILS.no_records, honorifics=COUNCILS.honorifics,
                        evidence_notes=re.compile(EVIDENCE_NOTES_STRICT.pattern + r"|the first council", re.I))
    differences = again(f, COUNCILS, verifier=excusing)
    assert said(differences) == {
        ("status", "This makes Northbridge the first council in the county to do so.", "unsupported", "connective",
         "weaker"),
        ("unsupported_segments", None, 1, 0, "weaker"),
        ("grounded_ratio", None, 0.557, 1.0, "weaker"),
    }
    with pytest.raises(AssertionError) as failed:
        assert_never_weaker(differences)
    message = str(failed.value)
    assert "have weakened in 3 places" in message
    assert ("uncited_claim: status in 'This makes Northbridge the first council in the county to do so.' was "
            "'unsupported' and is now 'connective' (weaker)") in message


def test_the_wide_rule_for_notes_is_weaker_than_the_strict_one_and_the_strict_one_stricter():
    """Where Councils Stand's rule against Where MPs Stand's (MIGRATION.md, 1.4): the one sentence they class
    differently is found, each way."""
    strict_first = again(report(fixture(), COUNCILS), COUNCILS, verifier=Verifier(
        no_records=COUNCILS.no_records, honorifics=COUNCILS.honorifics, evidence_notes=MPS.evidence_notes))
    assert said(strict_first) == {("status", NOTE, "unsupported", "connective", "weaker"),
                                  ("unsupported_segments", None, 2, 1, "weaker"),
                                  ("grounded_ratio", None, 0.36, 0.471, "weaker")}
    with pytest.raises(AssertionError, match="weakened in 3 places"):
        assert_never_weaker(strict_first)

    wide_first = again(report(fixture(), MPS), MPS, verifier=Verifier(
        no_records=MPS.no_records, honorifics=MPS.honorifics, evidence_notes=COUNCILS.evidence_notes))
    assert said(wide_first) == {("status", NOTE, "connective", "unsupported", "stricter"),
                                ("unsupported_segments", None, 1, 2, "stricter"),
                                ("grounded_ratio", None, 0.471, 0.36, "stricter")}
    assert_never_weaker(wide_first)  # stricter passes: it is for a person to read


def test_a_word_taken_off_the_list_is_weaker_and_one_added_is_stricter():
    f = report(fixture(), MPS)
    shorter = LoadedWords(re.compile(rf"\b({COMMON_LOADED_WORDS.replace('slammed|', '')})\b", re.I))
    assert said(again(f, MPS, loaded=shorter)) == {("loaded_words", CLAIM[2:], "slammed", None, "weaker"),
                                                   ("loaded_words", None, 1, 0, "weaker")}
    with pytest.raises(AssertionError, match="weakened in 2 places"):
        assert_never_weaker(again(f, MPS, loaded=shorter))

    longer = LoadedWords(re.compile(rf"\b({COMMON_LOADED_WORDS}|scrap)\b", re.I))
    differences = again(f, MPS, loaded=longer)
    assert said(differences) == {("loaded_words", "It also resolved to scrap them next year.", None, "scrap", "stricter"),
                                 ("loaded_words", None, 1, 2, "stricter")}
    assert_never_weaker(differences)


def test_a_citation_that_no_longer_stands_is_stricter_and_one_that_now_stands_is_weaker():
    # by hand: the two citations that stand are 58 and 70 characters, the claim 102 and the invalid citation 42,
    # so 128 of 272 characters are grounded (0.471); 70 of 272 when the first no longer stands (0.257); 170 of 272
    # when the third now does (0.625)
    f = report(fixture(), MPS)
    # the minutes no longer hold the words cited from Northbridge
    changed = (replace(DOCUMENTS[0], passages=("The Cabinet deferred the item.", DOCUMENTS[0].passages[1])),
               DOCUMENTS[1])
    cited = "weekly collections of food waste would begin in April 2026"
    differences = again(replace(f, documents=changed), MPS)
    assert said(differences) == {("status", cited, "cited", "invalid", "stricter"),
                                 ("citations", cited, (1,), (), "stricter"),
                                 ("citations_invalid", None, 1, 2, "stricter"),
                                 ("grounded_ratio", None, 0.471, 0.257, "stricter")}
    assert_never_weaker(differences)
    # the minutes now hold the words the invalid citation gave
    changed = (DOCUMENTS[0], replace(DOCUMENTS[1], passages=(*DOCUMENTS[1].passages,
                                                             "The Council resolved to scrap fortnightly collections.")))
    differences = again(replace(f, documents=changed), MPS)
    assert said(differences) == {("status", "It also resolved to scrap them next year.", "invalid", "cited", "weaker"),
                                 ("citations", "It also resolved to scrap them next year.", (), (2,), "weaker"),
                                 ("citations_invalid", None, 1, 0, "weaker"),
                                 ("grounded_ratio", None, 0.471, 0.625, "weaker")}
    with pytest.raises(AssertionError):
        assert_never_weaker(differences)


def test_a_quotation_no_longer_found_is_stricter_and_one_now_found_is_weaker():
    f = report(fixture(), MPS)
    lost = (replace(DOCUMENTS[0], passages=(DOCUMENTS[0].passages[0], "Cllr. Shah spoke about the old contract.")),
            DOCUMENTS[1])
    differences = again(replace(f, documents=lost), MPS)
    assert said(differences) == {("quotations", CLAIM[2:], "found", "not found", "stricter"),
                                 ("quotes_unverified", None, 1, 2, "stricter")}
    found = (replace(DOCUMENTS[0], passages=(*DOCUMENTS[0].passages, "He called it a complete waste of time.")),
             DOCUMENTS[1])
    differences = again(replace(f, documents=found), MPS)
    assert said(differences) == {("quotations", CLAIM[2:], "not found", "found", "weaker"),
                                 ("quotes_unverified", None, 1, 0, "weaker")}


def test_a_change_of_spelling_is_named_as_text_and_is_neither_stricter_nor_weaker():
    """The report recorded before a spelling rule: its words differ, its flags do not, and nothing is called
    weaker for a word having grown by a letter."""
    f = report(fixture(), MPS)
    assert f.report is not None
    before = json.loads(json.dumps(f.report).replace("favoured a new programme", "favored a new program"))
    differences = again(replace(f, report=before), MPS)
    lead_in = ("- Northbridge's Cabinet favoured a new programme: weekly collections of food waste would begin in "
               "April 2026.")
    assert said(differences) == {("text", lead_in, "favored", "favoured", "other"),
                                 ("text", lead_in, "program:", "programme:", "other")}
    assert_never_weaker(differences)


def test_a_flag_lost_in_words_that_also_changed_is_still_weaker():
    f = report(fixture(), MPS)
    assert f.report is not None
    before = json.loads(json.dumps(f.report))
    claim = before["segments"][3]
    assert claim["text"].startswith(". Cllr. Shah slammed")
    # as if the briefing had been recorded with another word, marked as loaded, where "slammed" now stands unmarked
    claim["text"] = claim["text"].replace("slammed", "blasted")
    claim["loaded"] = [{"start": 13, "end": 20, "word": "blasted"}]
    without = LoadedWords(re.compile(r"\b(blasted)\b", re.I))
    differences = again(replace(f, report=before), MPS, loaded=without)
    assert ("loaded_words", "Cllr. Shah slammed the old contract as \"a poor use of public money\" and \"a complete "
            "waste of time\".", "blasted", None, "weaker") in said(differences)
    assert ("loaded_words", None, 1, 0, "weaker") in said(differences)
    assert any(d.check == "text" and d.kind == "other" for d in differences)


def test_a_passage_split_in_two_with_the_same_marks_is_no_difference():
    f = report(fixture(), MPS)
    assert f.report is not None
    before = json.loads(json.dumps(f.report))
    first = before["segments"][0]
    half = len(first["text"]) // 2
    before["segments"][0:1] = [{**first, "text": first["text"][:half]}, {**first, "text": first["text"][half:]}]
    assert again(replace(f, report=before), MPS) == []


def test_a_difference_reads_as_a_sentence():
    d = Difference("wind", "status", "Costs rose sharply.", "unsupported", "connective", "weaker")
    assert str(d) == "wind: status in 'Costs rose sharply.' was 'unsupported' and is now 'connective' (weaker)"
    assert str(Difference("wind", "citations_invalid", None, 0, 1, "stricter")) == (
        "wind: citations_invalid was 0 and is now 1 (stricter)")
    assert_never_weaker([])


# ---- fixtures on disk ------------------------------------------------------------------------------------------


def test_a_fixture_is_saved_and_read_back_whole(tmp_path):
    f = report(fixture("bins"), COUNCILS)
    path = save_fixture(f, tmp_path)
    assert path == tmp_path / "bins.jsonl" and (tmp_path / "bins.report.json").is_file()
    assert load_fixture(path) == f
    assert again(load_fixture(path), COUNCILS) == []
    # it is a recording like any other: its header says what was asked, and a scripted model can replay it
    assert load_header(path)["question"] == QUESTION and load_header(path)["headings"] == list(HEADINGS)
    assert ScriptedModel(path).script == [Completed(BLOCKS, "", None, Usage())]


def test_a_fixture_without_a_report_can_be_checked_but_not_replayed(tmp_path):
    path = save_fixture(fixture("bins"), tmp_path)
    assert not (tmp_path / "bins.report.json").exists()
    loaded = load_fixture(path)
    assert loaded.report is None and loaded.blocks == BLOCKS and loaded.documents == DOCUMENTS
    with pytest.raises(ValueError, match="'bins' has no recorded report"):
        replay([loaded], COUNCILS.verifier, COUNCILS.loaded_words)
    with pytest.raises(FileNotFoundError):
        load_fixture(path, report=tmp_path / "elsewhere.json")


def test_a_recording_of_a_stream_that_never_finished_is_no_fixture(tmp_path):
    path = record_stream(tmp_path / "cut.jsonl", [], documents=DOCUMENTS)
    with pytest.raises(ValueError, match="no finished message"):
        load_fixture(path)


def test_a_shipped_recording_is_a_fixture_as_it_stands():
    f = load_fixture(recorded("real_cited_briefing"))
    assert f.name == "real_cited_briefing" and f.report is None and f.headings == ()
    assert f.question == "What did these councils decide about waste collections and recycling?"
    assert len(f.documents) == 3 and isinstance(f.documents[0], Document)
    assert isinstance(f.blocks[0], Block) and any(isinstance(c, Citation) for b in f.blocks for c in b.citations)
