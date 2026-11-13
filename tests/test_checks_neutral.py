"""Loaded words (wts_core.checks.neutral): the sites' tests, run with each site's own list."""

from __future__ import annotations

import re

import pytest

from checks_sites import COUNCILS, COUNTRIES, MPS, SITES, SiteChecks, src
from wts_core.checks import COMMON_LOADED_WORDS, LoadedWords, Segment


@pytest.fixture(params=SITES, ids=lambda s: s.name)
def site(request: pytest.FixtureRequest) -> SiteChecks:
    return request.param


def words(site: SiteChecks, text: str) -> list[str]:
    seg = Segment(text)
    site.loaded_words.flag([seg])
    return [m["word"] for m in seg.loaded]


# ---- from Where MPs Stand's tests/test_british.py ---------------------------------------------------------------


def test_loaded_words_are_flagged_only_outside_quotations(site):
    segs = [Segment("The minister admitted the delay and ", status="connective"),
            Segment('said "this was a scandal', status="cited"),
            Segment('" before benefit claims rose; MPs attacked it.', status="connective")]
    assert site.loaded_words.flag(segs) == 2
    found = [(i, f["word"]) for i, s in enumerate(segs) for f in s.loaded]
    assert found == [(0, "admitted"), (2, "attacked")]
    f = segs[0].loaded[0]
    assert segs[0].text[f["start"]:f["end"]] == "admitted"


def test_claimed_counts_only_as_a_verb_of_saying(site):
    assert not site.loaded.search("He questioned the benefits claimed for the trial and the claimed savings.")
    assert site.loaded.search("Jones claimed that the plan had failed.") and site.loaded.search("as Smith claimed, ")
    saved = {"segments": [{"text": "He questioned the benefits claimed for the trial", "status": "connective",
                           "loaded": [{"start": 31, "end": 38, "word": "claimed"}]},
                          {"text": "Jones claimed that it failed", "status": "connective",
                           "loaded": [{"start": 6, "end": 13, "word": "claimed"}]}], "loaded_words": 2}
    out = site.loaded_words.still_loaded(saved)
    assert out["loaded_words"] == 1 and not out["segments"][0]["loaded"] and out["segments"][1]["loaded"]


# ---- from Where Countries Stand's tests/test_rag.py and tests/test_pipeline.py ----------------------------------


def test_labels_for_governments_and_blocs_are_where_countries_stands_own():
    report = COUNTRIES.verifier.verify(
        [{"text": "France said its action was self-defence", "citations": [
            {"search_result_index": 0, "cited_text": "Our action is self-defence."}]},
         {"text": ", while the regime in question ignored the West.", "citations": []}],
        [src(1, "Our action is self-defence.")])
    found = [m["word"] for s in report.segments for m in s.loaded] if COUNTRIES.loaded_words.flag(report.segments) else []
    assert "regime" in found and "the West" in found
    # "the West" as a bloc, only with its capital letter
    assert all(s.loaded_words.flag([Segment("Troops moved to the west of the country.")]) == 0 for s in SITES)
    assert words(MPS, ", while the regime in question ignored the West.") == []
    assert words(COUNCILS, ", while the regime in question ignored the West.") == []


def test_a_loaded_word_in_the_models_own_voice_is_counted_on_the_answer():
    blocks = [{"text": "Kenya said "},
              {"text": "climate finance for adaptation is too slow", "citations": [
                  {"search_result_index": 0, "cited_text": "Kenya says climate finance for adaptation is too slow."}]},
              {"text": " The regime was mentioned."}]
    answer = COUNTRIES.check(blocks, [src(1, "Kenya says climate finance for adaptation is too slow.")])
    assert answer["citations_total"] == 1 and answer["citations_invalid"] == 0
    assert "[Source 1]" in answer["markdown"] and answer["loaded_words"] == 1


# ---- from Where Councils Stand's tests/test_pipeline.py ---------------------------------------------------------


def test_a_word_about_a_councils_conduct_is_where_councils_stands_own():
    quote = "The council agreed to restore weekly bin collections from April."
    blocks = [{"text": "The minutes record that "},
              {"text": quote[:60], "citations": [{"search_result_index": 0, "cited_text": quote, "source": "x"}]},
              {"text": " The scheme was a fiasco that residents across the borough opposed for many months."}]
    answer = COUNCILS.check(blocks, [src(1, quote)])
    assert answer["citations_total"] == 1 and answer["citations_invalid"] == 0
    assert answer["unsupported_segments"] == 1  # the uncited sentence is marked, not passed off as sourced
    assert answer["loaded_words"] == 1          # "fiasco" in the model's own voice is flagged
    assert MPS.check(blocks, [src(1, quote)])["loaded_words"] == 0


# ---- each site's list -------------------------------------------------------------------------------------------


def test_each_site_flags_the_common_words_and_its_own():
    """The study's probe (docs/study/ai-slice.md, section 2)."""
    text = "The regime admitted the scheme was a fiasco; the West claimed that it was reckless and far-right."
    assert words(MPS, text) == ["admitted", "claimed"]
    assert words(COUNTRIES, text) == ["regime", "admitted", "the West", "claimed"]
    assert words(COUNCILS, text) == ["admitted", "fiasco", "claimed", "reckless", "far-right"]


def test_every_common_word_is_flagged_by_every_site_whatever_its_capitals(site):
    common = re.sub(r"\(\?=.*?\$\)", "", COMMON_LOADED_WORDS).split("|")  # without the rule for "claimed"
    assert len(common) == 38 and "claimed" in common and "refused to answer" in common
    for word in common:
        text = f"It was said that they {word.upper() if word != 'claimed' else 'Claimed'} that it was so."
        assert [w.lower() for w in words(site, text)] == [word], word
    # and none inside a longer word
    assert words(site, "The unadmitted scandalmonger was preattacked.") == []


def test_the_common_words_alone_are_where_mps_stands_whole_list():
    assert MPS.loaded.pattern == rf"\b({COMMON_LOADED_WORDS})\b" and MPS.loaded.flags & re.IGNORECASE
    assert all(COMMON_LOADED_WORDS in s.loaded.pattern for s in SITES)


def test_nothing_is_ever_newly_marked_when_a_saved_briefing_is_shown_again(site):
    lw = site.loaded_words
    assert lw.still_loaded(None) is None and lw.still_loaded({}) == {} and lw.still_loaded({"segments": []}) == {
        "segments": []}
    unmarked = {"segments": [{"text": "Ministers admitted the delay.", "status": "unsupported"},
                             {"text": "They lied.", "status": "unsupported", "loaded": []}], "loaded_words": 0}
    assert lw.still_loaded(unmarked) is unmarked  # words the list has since gained are not marked on old briefings
    saved = {"segments": [{"text": "Ministers admitted the delay.", "status": "unsupported", "loaded": [
        {"start": 10, "end": 18, "word": "admitted"},   # still on the list
        {"start": 10, "end": 17, "word": "admitte"},    # no longer what the list matches there
        {"start": 23, "end": 28, "word": "delay"}]},    # not on the list
        {"text": "No marks here.", "status": "connective"}], "loaded_words": 3, "rules": 1}
    out = lw.still_loaded(saved)
    assert out["segments"][0]["loaded"] == [{"start": 10, "end": 18, "word": "admitted"}] and out["loaded_words"] == 1
    assert out["segments"][1] is saved["segments"][1] and out["rules"] == 1
    assert len(saved["segments"][0]["loaded"]) == 3  # the saved answer itself is not changed


def test_the_list_is_passed_in_whole():
    own = LoadedWords(re.compile(r"\b(splendid)\b", re.IGNORECASE))
    seg = Segment('A splendid plan, which ministers admitted was "splendid".')
    assert own.flag([seg]) == 1 and seg.loaded == [{"start": 2, "end": 10, "word": "splendid"}]
