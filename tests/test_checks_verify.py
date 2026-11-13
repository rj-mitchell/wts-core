"""The citation verifier (wts_core.checks.verify): every test the three sites have for their copies, run with each
site's own inputs, and the tests of what the package adds (the stamp of the rules' version).

Where a site's inputs change the answer (Where Councils Stand's honorifics, and its strict form of the "note about
the evidence" rule), the test says so for each site: that is the behaviour its readers have today.
"""

from __future__ import annotations

import pytest

from checks_sites import COUNCILS, COUNTRIES, MPS, SITES, WIDE, SiteChecks, Source, src
from wts_core.checks import (
    COMMON_HONORIFICS,
    EVIDENCE_NOTES_STRICT,
    EVIDENCE_NOTES_WIDE,
    RULES_VERSION,
    Segment,
    SourceText,
    TitledSource,
    Verification,
    Verifier,
    curl_answer,
    curl_events,
)
from wts_core.checks.verify import _found, _words


@pytest.fixture(params=SITES, ids=lambda s: s.name)
def site(request: pytest.FixtureRequest) -> SiteChecks:
    return request.param


@pytest.fixture
def v(site: SiteChecks) -> Verifier:
    return site.verifier


def statuses(segments) -> list[str]:
    return [s.status for s in segments]


# ---- from Where MPs Stand's tests/test_rag.py -------------------------------------------------------------------


def test_verify_marks_cited_unsupported_and_invalid(v):
    sources = [src(1, "The line to Crewe is delayed by two years.", "Costs rose sharply."), src(2, "We oppose it.")]
    blocks = [
        {"text": "Ministers said ", "citations": []},
        {"text": "the Crewe line is delayed by two years", "citations": [
            {"search_result_index": 0, "cited_text": "The line to Crewe is delayed by two years."}]},
        {"text": ". The project was also cancelled in 2023 because of a scandal.", "citations": []},
        {"text": "Opponents disagreed", "citations": [{"search_result_index": 1, "cited_text": "Text not in source"}]},
    ]
    report = v.verify(blocks, sources)
    assert statuses(report.segments) == ["connective", "cited", "unsupported", "invalid"]
    assert report.citations_total == 2 and report.citations_invalid == 1
    assert "[Source 1]" in report.markdown() and "[Source 2]" not in report.markdown()
    assert 0 < report.grounded_ratio < 1
    assert not report.no_records


def test_verify_separates_lead_ins_and_evidence_notes_from_uncited_claims(v):
    sources = [src(1, "We will deliver the line to Manchester.")]
    cite = {"search_result_index": 0, "cited_text": "We will deliver the line to Manchester."}
    blocks = [
        {"text": "## Labour MPs\n\n**Shadow ministers**\n\n"
                 "Shadow ministers attacked the decision to cancel the northern legs.\n"
                 "- Louise Haigh (Sheffield Heeley, Lab), 4 October 2023, said ", "citations": []},
        {"text": "the line to Manchester would be delivered", "citations": [cite]},
        {"text": ".\n\nNo division records were supplied, so votes cannot be reported.\n"
                 "- The retrieved records contain no revised opening date.\n"
                 "- Two results on prison building were not relevant and have been excluded.\n"
                 "- The records are dominated by compensation. Little was found on the system itself.", "citations": []},
    ]
    report = v.verify(blocks, sources)
    by_status: dict[str, list[str]] = {}
    for s in report.segments:
        by_status.setdefault(s.status, []).append(s.text)
    unsupported = "".join(by_status["unsupported"])
    assert "attacked the decision" in unsupported
    assert "Louise Haigh" not in unsupported and "Labour MPs" not in unsupported
    assert "No division records" not in unsupported
    assert "opening date" not in unsupported and "prison" not in unsupported and "dominated" not in unsupported
    assert report.to_dict()["unsupported_segments"] == 1


def test_verify_detects_no_records_answer(site, v):
    report = v.verify([{"text": f"{site.no_records} The records cover only fisheries.", "citations": []}], [src(1, "x")])
    assert report.no_records


def test_the_no_records_words_are_the_sites_own():
    v = Verifier(no_records="Nothing was found.", evidence_notes=EVIDENCE_NOTES_STRICT)
    assert v.verify([{"text": "\nNothing was found. The minutes cover only fisheries."}], []).no_records
    assert not v.verify([{"text": "No records found. The minutes cover only fisheries."}], []).no_records


def test_quotations_are_checked_word_for_word(v):
    sources = [Source(1, "record", "t", "u", ["I very much support renewable energy, but we now have our fair share of "
                                              "onshore wind. I warmly welcome the hon. and learned Gentleman's point."], {})]
    segs = [Segment('Lamont said "I very much support renewable energy" ', [], status="connective"),
            Segment('and "we now have our fair share … onshore wind."', [1]),
            Segment(' He "warmly welcome[d] the hon. and learned Gentleman".', [1]),
            Segment(' He also said "wind farms are a blight on the landscape".', [1]),
            Segment(' The term "net zero" is not a quotation.', [], status="connective")]
    report = Verification(segs, False, 3, 0, 0, 10)
    assert v.check_quotes(report, sources) == 1
    assert (report.quotes_total, report.quotes_unverified) == (4, 1)
    assert segs[3].misquotes == [{"start": 14, "end": 56, "text": "wind farms are a blight on the landscape"}]
    assert report.to_dict()["quotes_unverified"] == 1


def test_a_word_printed_twice_in_the_record_does_not_make_a_misquote():
    record = _words("but more with the positioning of of that company, where its profits are made")
    assert _found("more with the positioning of that company", record)
    assert not _found("the positioning of the company", record)


def test_the_closing_note_about_the_evidence_is_not_a_claim(v):
    note = v._classify_uncited("\n**About the evidence:** the records span 2013 to 2026 and include no divisions.\n", False)
    assert statuses(note) == ["connective"]
    note = v._classify_uncited("\nAbout the evidence: the records show what was said, but nothing said by Hilary Benn "
                               "before 2026.\n", False)
    assert statuses(note) == ["connective"]
    claim = v._classify_uncited("\nAbout the evidence: Jane Smith said the policy had failed families across the "
                                "country.\n", False)
    assert "unsupported" in statuses(claim)  # a claim about what someone said still needs a citation


def test_a_lead_in_after_an_uncited_sentence_is_not_flagged_but_the_sentence_is(v):
    segs = v._classify_uncited("Labour MPs criticised the government. Jane Smith said on 4 May that ", True)
    assert [(s.status, s.text) for s in segs] == [("unsupported", "Labour MPs criticised the government. "),
                                                   ("connective", "Jane Smith said on 4 May that ")]
    assert statuses(v._classify_uncited("- Keir Mather (Selby), 10 August 2026, said ", True)) == ["connective"]


def test_the_date_after_a_citation_is_not_flagged(v):
    for when in (" (16 September 2025).\n", " (March 2024)", " (2019),\n", " on 12 November 2025.\n",
                 " (written answer, 12 October 2026).\n"):
        assert statuses(v._classify_uncited(when, False)) == ["connective"], when
    assert statuses(v._classify_uncited(" (16 September 2025), when it rose by 4%.\n", False)) == ["unsupported"]


def test_openers_about_the_records_are_dropped(v):
    segs = [Segment("Across the records retrieved, ministers defended the policy."),
            Segment("**In brief**\n- In the records supplied, Labour MPs criticised it."),
            Segment("In 2019 the minister said so.")]
    assert v.drop_preambles(segs) == 2
    assert [s.text for s in segs] == ["Ministers defended the policy.", "**In brief**\n- Labour MPs criticised it.",
                                      "In 2019 the minister said so."]


def test_saved_briefings_are_rechecked_by_the_current_rules(v):
    answer = {"segments": [{"text": "X said it worked", "status": "cited"},
                           {"text": " (16 September 2025).\n", "status": "unsupported"},
                           {"text": "Prices rose by 4% in the year to March, the fastest rise since 1992.",
                            "status": "unsupported"}],
              "unsupported_segments": 2, "grounded_ratio": 0.3}
    out = v.recheck(answer)
    assert [s["status"] for s in out["segments"]] == ["cited", "connective", "unsupported"]
    assert out["unsupported_segments"] == 1 and out["grounded_ratio"] == round(16 / (16 + 68), 3)
    assert v.recheck({"segments": []}) == {"segments": []} and v.recheck(None) is None


def test_the_devolution_note_is_not_a_point_to_check(v):
    for note in ("These bodies decide many of these subjects for their own nations. ",
                 "These bodies decide many matters for their own nations and are not the UK Parliament. ",
                 "The Senedd is a separate parliament that decides education for Wales. ",
                 "These bodies decide different matters from Westminster. ",
                 "The Senedd decides many subjects for Wales, so this was a decision on consent. "):
        assert statuses(v._classify_uncited(note, False)) == ["connective"], note
    # the full stop closing one citation, before the lead-in to the next
    assert statuses(v._classify_uncited(". Jane Smith said that ", True)) == ["connective"]


def test_a_citation_across_two_paragraphs_is_accepted(v):
    source = Source(1, "record", "A member", "u", ["(3) The assessment must estimate the cost of—",
                                                   "(a) implementation of this Act, and", "(b) the cap."])
    block = {"text": "It sought a cost estimate", "citations": [{"search_result_index": 0, "cited_text":
             "the cost of—(a) implementation of this Act, and(b) the cap."}]}
    report = v.verify([block], [source])
    assert report.citations_invalid == 0 and report.segments[0].status == "cited"
    wrong = {"text": "x", "citations": [{"search_result_index": 0, "cited_text": "the costs of—(a) implementation"}]}
    assert v.verify([wrong], [source]).citations_invalid == 1


def test_an_honorifics_full_stop_ends_no_sentence(v):
    # "Mr. " no longer reads as the end of a sentence, so the whole line leads in to the quotation after it
    segs = v._classify_uncited("- Giving evidence to the Transport Committee on the northern legs, Mr. Smith said ", True)
    assert statuses(segs) == ["connective"]
    # a claim before the lead-in is still split off and flagged, and the text kept is the original
    segs = v._classify_uncited("Witnesses doubted the figures. Dr. Jones told the committee that ", True)
    assert [(s.status, s.text) for s in segs] == [("unsupported", "Witnesses doubted the figures. "),
                                                   ("connective", "Dr. Jones told the committee that ")]


def test_a_lead_in_written_in_pieces_is_not_a_claim(v):
    sources = [src(1, "The line to Manchester will be delivered in full.")]
    blocks = [{"text": "- Witnesses from the industry differed sharply on the timetable, as when its chief executive, "
                       "Mr. "}, {"text": "Stephens said "},
              {"text": '"The line to Manchester will be delivered in full."', "citations": [
                  {"search_result_index": 0, "cited_text": "The line to Manchester will be delivered in full."}]},
              {"text": " The project was then cancelled in 2023 because of a scandal. "}]
    assert statuses(v.verify(blocks, sources).segments) == ["connective", "connective", "cited", "unsupported"]
    # a whole sentence in between is a claim, and the piece before it leads in to nothing
    blocks[1] = {"text": "The company had overspent on the northern section by more than a billion pounds. "}
    assert statuses(v.verify(blocks, sources).segments)[:3] == ["unsupported", "unsupported", "cited"]


VOTE_DATA_NOTES = ("No recorded-vote data was available for any of the debates on this subject. ",
                   "Division lists for the debates in the Lords in this period were not supplied. ",
                   "The votes on the second reading were not supplied, so how members voted is unknown. ")


@pytest.mark.parametrize("site", WIDE, ids=lambda s: s.name)
def test_notes_that_data_was_not_supplied_are_not_claims(site):
    for note in VOTE_DATA_NOTES:
        assert statuses(site.verifier._classify_uncited(note, False)) == ["connective"], note


def test_the_strict_form_of_the_rule_takes_those_notes_for_claims_as_where_councils_stand_does_today():
    """The price of the strict form: real notes about missing vote data are points to check (MIGRATION.md 1.4)."""
    for note in VOTE_DATA_NOTES:
        assert statuses(COUNCILS.verifier._classify_uncited(note, False)) == ["unsupported"], note


def test_only_the_wide_form_of_the_rule_lets_a_claim_about_something_supplied_pass():
    """What the strict form is for: "was supplied" in an ordinary claim is no note about the evidence. A site given
    the strict form must flag it, case for case; the wide form is what the other two sites have today."""
    claim = "Gas was supplied to two million homes by the company in that year alone, they found. "
    assert statuses(COUNCILS.verifier._classify_uncited(claim, False)) == ["unsupported"]
    for site in WIDE:
        assert statuses(site.verifier._classify_uncited(claim, False)) == ["connective"], site.name
    # everything the strict form takes for a note, the wide form does too: the wide form only ever clears more
    assert EVIDENCE_NOTES_WIDE.pattern != EVIDENCE_NOTES_STRICT.pattern
    for note in ("No division records were supplied, so votes cannot be reported.", "There are gaps in the minutes.",
                 "Votes cannot be attributed to members.", "Notes: the records cover two meetings."):
        assert EVIDENCE_NOTES_STRICT.search(note) and EVIDENCE_NOTES_WIDE.search(note), note


def test_saved_briefings_with_a_lead_in_in_pieces_are_cleared(v):
    answer = {"segments": [{"text": "- Witnesses from the industry differed sharply on the timetable, as when Mr. ",
                            "status": "unsupported"},
                           {"text": "Stephens said ", "status": "connective"},
                           {"text": "\"it will be delivered\"", "status": "cited"}],
              "unsupported_segments": 1, "grounded_ratio": 0.5}
    out = v.recheck(answer)
    assert [s["status"] for s in out["segments"]] == ["connective", "connective", "cited"]
    assert out["unsupported_segments"] == 0 and out["grounded_ratio"] == 1.0


# each site's own wording of the next two tests (tests/test_rag.py in two, tests/test_verify.py in the third)
SHORT_CLAIMS = ("Labour MPs criticised the government. Jane Smith said on 4 May that ",
                "Several delegations criticised the draft. France's representative said on 4 May that ",
                "Opposition councillors criticised the budget. Cllr Jones said on 4 May that ")
CLAIMS_ABOVE = tuple(block + who for who in ("Jane Smith said ", "France's representative said ", "Cllr Jones said ")
                     for block in ("- Spending on the scheme rose by 40% under the last administration\n- ",
                                   "Was the funding cut by 40% in real terms? ",
                                   "The scheme was cut by 40% in real terms! "))


@pytest.mark.parametrize("block", SHORT_CLAIMS)
def test_a_short_claim_stays_a_point_to_check_when_a_saved_briefing_is_shown_again(v, block):
    # verify() splits a whole sentence off a lead-in and marks it as a claim, however short it is
    parts = v._classify_uncited(block, True)
    assert statuses(parts) == ["unsupported", "connective"]
    answer = {"segments": [*({"text": p.text, "status": p.status} for p in parts),
                           {"text": "\"it has failed\"", "status": "cited"}],
              "unsupported_segments": 1, "grounded_ratio": 0.3}
    # shown again, it is judged without that knowledge: being short must not clear it
    assert v.recheck(answer) is answer


@pytest.mark.parametrize("block", CLAIMS_ABOVE)
def test_a_claim_above_a_lead_in_stays_a_point_to_check_when_shown_again(v, block):
    parts = v._classify_uncited(block, True)
    assert statuses(parts) == ["unsupported", "connective"], block
    answer = {"segments": [*({"text": p.text, "status": p.status} for p in parts),
                           {"text": "\"it has failed\"", "status": "cited"}],
              "unsupported_segments": 1, "grounded_ratio": 0.3}
    # judged again without the block it was written in, it must not pass for the opening of the quotation
    assert v.recheck(answer) is answer, block


# ---- from Where Countries Stand's tests/test_rag.py and tests/test_api.py ----------------------------------------


def test_a_valid_citation_names_its_source(v):
    blocks = [{"text": "France said its action was self-defence", "citations": [
        {"search_result_index": 0, "cited_text": "Our action is self-defence."}]},
        {"text": ", while the regime in question ignored the West.", "citations": []}]
    report = v.verify(blocks, [src(1, "Our action is self-defence.")])
    assert report.citations_invalid == 0 and report.segments[0].sources == [1]


def test_lead_ins_in_pieces_are_not_claims(v):
    """Found in real briefings: the model writes a lead-in in pieces, and an honorific's full stop ends no sentence."""
    sources = [Source(1, "record", "t", "u", ["The use of force is not justified at this time."])]
    blocks = [{"text": "- Members differed, as when France's Mr. "}, {"text": "Galouzeau De Villepin said "},
              {"text": '"The use of force is not justified at this time."',
               "citations": [{"search_result_index": 0, "cited_text": "The use of force is not justified at this time."}]},
              {"text": " The United States then voted against every resolution on the subject since 1992. "}]
    assert statuses(v.verify(blocks, sources).segments) == ["connective", "connective", "cited", "unsupported"]


def test_saved_briefings_are_shown_with_flags_judged_again(site):
    """A mark made by an older rule that has since been corrected (a lead-in taken for an unsupported claim, a
    neutral "claimed" taken for a loaded word) is not shown on a briefing saved before the correction."""
    answer = {"markdown": "Kenya said climate finance is slow. The savings claimed were large.",
              "segments": [{"text": "Kenya said ", "status": "unsupported"},
                           {"text": "climate finance is slow.", "status": "cited", "sources": [1]},
                           {"text": " The savings claimed were large.", "status": "cited", "sources": [1],
                            "loaded": [{"start": 13, "end": 20, "word": "claimed"}]}],
              "unsupported_segments": 1, "grounded_ratio": 0.5, "loaded_words": 1}
    shown = site.shown_again(answer)
    assert shown["segments"][0]["status"] == "connective" and shown["unsupported_segments"] == 0
    assert shown["loaded_words"] == 0 and shown["segments"][2]["loaded"] == []


def test_saved_briefings_are_shown_with_curly_quotes():
    """A briefing saved before quotes were curled is shown with them curled, its marks where they were."""
    text = 'Kenya called it "too slow" and the Council\'s regime was mentioned.'
    mark = {"start": text.index("regime"), "end": text.index("regime") + 6, "word": "regime"}
    answer = {"segments": [{"text": text, "status": "cited", "sources": [1], "loaded": [mark]}], "loaded_words": 1}
    events = curl_events([{"type": "final", "answer": COUNTRIES.shown_again(answer)}])
    shown = events[-1]["answer"]["segments"][0]
    assert shown["text"] == "Kenya called it “too slow” and the Council’s regime was mentioned."
    assert shown["loaded"] == [mark] and shown["text"][mark["start"]:mark["end"]] == "regime"


def test_a_saved_curled_briefing_keeps_its_points_to_check(site):
    """The recheck reads a briefing saved with curly quotes as it read the straight ones: a sentence that ends in a
    closing quote is still a claim of its own, not a lead-in to the quotation after it."""
    answer = {"segments": [{"text": 'He said "no." Mr Smith said ', "status": "unsupported"},
                           {"text": "we will act", "status": "cited", "sources": [1]}],
              "unsupported_segments": 1}
    for saved in (answer, curl_answer(answer)):
        shown = curl_answer(site.verifier.recheck(saved, curled=True))["segments"][0]
        assert shown["status"] == "unsupported"
        assert shown["text"] == "He said “no.” Mr Smith said "


def test_read_with_straight_quotes_a_curled_briefing_gets_its_statuses_and_keeps_its_text(v):
    saved = {"segments": [{"text": "Kenya’s delegate said “", "status": "unsupported"},
                          {"text": "climate finance is slow", "status": "cited"},
                          {"text": "” (16 September 2025).\n", "status": "connective"}, {"status": "connective"}],
             "unsupported_segments": 1, "grounded_ratio": 0.5}
    out = v.recheck(saved, curled=True)
    assert [s.get("status") for s in out["segments"]] == ["connective", "cited", "connective", "connective"]
    assert [s.get("text") for s in out["segments"]] == [s.get("text") for s in saved["segments"]]
    assert out["unsupported_segments"] == 0 and out["grounded_ratio"] == 1.0
    kept = {"segments": [{"text": "It’s cut by 40% in real terms.", "status": "unsupported"}]}
    assert v.recheck(kept, curled=True) is kept and v.recheck({"segments": []}, curled=True) == {"segments": []}


# ---- from Where Councils Stand's tests/test_verify.py -----------------------------------------------------------

QUOTE = "The council agreed to restore weekly bin collections from April."
SRC = [Source(1, "minutes", "Full Council", "https://example/1", [QUOTE])]


def cited(text: str) -> dict:
    return {"text": text, "citations": [{"search_result_index": 0, "cited_text": QUOTE}]}


def test_a_lead_in_in_pieces_after_a_councillors_title_is_not_a_claim_where_the_title_is_an_honorific(site, v):
    """Found in real briefings: the model writes a lead-in in pieces, and an honorific's full stop ends no sentence.
    "Cllr." is one of Where Councils Stand's honorifics only: the other two sites cut the line at it, as today."""
    blocks = [{"text": "- Members differed on how often bins should be collected, as when the Leader, Cllr. "},
              {"text": "Jones said "}, cited(f'"{QUOTE}"'),
              {"text": " The opposition then voted against every budget since 2019. "}]
    first = "connective" if site is COUNCILS else "unsupported"
    assert statuses(v.verify(blocks, SRC).segments) == [first, "connective", "cited", "unsupported"]


def test_an_honorific_does_not_split_a_lead_in_into_a_claim(v):
    segs = v._classify_uncited("Mr. Smith, the portfolio holder, said ", next_is_cited=True)
    assert statuses(segs) == ["connective"]
    # a real sentence before the lead-in is still a claim, and the text is kept as written
    segs = v._classify_uncited("The vote was close. Mr. Smith said ", next_is_cited=True)
    assert statuses(segs) == ["unsupported", "connective"]
    assert "".join(s.text for s in segs) == "The vote was close. Mr. Smith said "


def test_a_long_uncited_piece_still_breaks_the_lead_in(v):
    blocks = [{"text": "Cllr. "}, {"text": "The council has cut every library budget since 2019 and closed six branches. "},
              cited(f'"{QUOTE}"')]
    found = statuses(v.verify(blocks, SRC).segments)
    assert found[-1] == "cited" and "unsupported" in found[:-1]


def test_a_saved_lead_in_ending_in_a_councillors_title_is_cleared_only_where_the_title_is_an_honorific(site, v):
    answer = {"segments": [{"text": "- Members differed sharply on the timetable, as when Cllr. ", "status": "unsupported"},
                           {"text": "Jones said ", "status": "connective"},
                           {"text": "\"it will be delivered\"", "status": "cited"}],
              "unsupported_segments": 1, "grounded_ratio": 0.5}
    out = v.recheck(answer)
    if site is not COUNCILS:
        assert out is answer
        return
    assert [s["status"] for s in out["segments"]] == ["connective", "connective", "cited"]
    assert out["unsupported_segments"] == 0 and out["grounded_ratio"] == 1.0


def test_a_sites_honorifics_are_added_to_the_common_ones():
    assert MPS.honorifics == COUNTRIES.honorifics == COMMON_HONORIFICS
    assert COUNCILS.honorifics == (*COMMON_HONORIFICS, "Cllr", "Rev", "Revd", "Hon")
    lead_in = "- Speaking for the administration at the budget meeting in February, Cllr. Jones said "
    assert statuses(COUNCILS.verifier._classify_uncited(lead_in, True)) == ["connective"]
    for site in (MPS, COUNTRIES):  # cut at "Cllr.", so the line before it is taken for a claim
        assert statuses(site.verifier._classify_uncited(lead_in, True)) == ["unsupported", "connective"]
    for title in ("Rev", "Revd", "Hon"):
        assert statuses(COUNCILS.verifier._classify_uncited(f"The vote was close. {title}. Green said ", True)) == [
            "unsupported", "connective"]
    # as written, capital letter and all: Hansard's "the hon. Member" is cut at "hon." in every site
    assert all("unsupported" in statuses(s.verifier._classify_uncited(
        "- Replying to the debate on the northern legs for the Opposition, the hon. Member said ", True)) for s in SITES)


# ---- cases no site tests (docs/study/ai-slice.md, section 1) -----------------------------------------------------


def test_an_invalid_citation_counts_against_the_ratio_but_is_not_an_unsupported_segment(v):
    sources = [src(1, "Costs rose sharply.")]
    blocks = [{"text": "Costs rose", "citations": [{"search_result_index": 0, "cited_text": "Costs rose sharply."}]},
              {"text": "Costs fell", "citations": [{"search_result_index": 0, "cited_text": "Costs fell sharply."}]},
              {"text": "Costs rose", "citations": [{"search_result_index": 7, "cited_text": "Costs rose sharply."}]}]
    answer = v.verify(blocks, sources).to_dict()
    assert [s["status"] for s in answer["segments"]] == ["cited", "invalid", "invalid"]
    assert answer["citations_invalid"] == 2 and answer["unsupported_segments"] == 0
    assert answer["grounded_ratio"] == round(10 / 30, 3)


def test_a_block_is_cited_when_one_of_its_citations_holds_and_names_each_source_once(v):
    sources = [src(1, "Costs rose sharply.", "The line is late."), src(2, "We oppose it.")]
    block = {"text": "Costs rose and the line is late", "citations": [
        {"search_result_index": 0, "cited_text": "Costs rose sharply."},
        {"search_result_index": 0, "cited_text": "The line is late."},
        {"search_result_index": 1, "cited_text": "We support it."},
        {"document_index": 1, "cited_text": "We oppose it."}]}  # the older key is read when the newer is absent
    report = v.verify([block], sources)
    seg = report.segments[0]
    assert seg.status == "cited" and seg.sources == [1, 2] and report.markdown().endswith(" [Source 1][Source 2]")
    assert (report.citations_total, report.citations_invalid) == (4, 1)
    assert seg.cited == [{"source": 1, "cited_text": "Costs rose sharply."},
                         {"source": 1, "cited_text": "The line is late."}, {"source": 2, "cited_text": "We oppose it."}]


def test_a_citation_is_checked_whatever_its_quote_marks_capitals_or_spacing(v):
    sources = [src(1, "He said: “It’s  not\njustified.”")]
    good = {"text": "x", "citations": [{"search_result_index": 0, "cited_text": "he said: \"it's not justified.\""}]}
    assert v.verify([good], sources).citations_invalid == 0


def test_quotations_in_single_curly_marks_are_checked_and_a_possessive_is_not_taken_for_one(v):
    sources = [src(1, "Climate finance is slow, and we know it.")]
    segs = [Segment("Kenya said ‘climate finance is slow’ ", [1]),
            Segment("and ‘finance will never arrive’. ", [1]),
            Segment("The ministers’ view of the councils’s budget was not given.", status="unsupported")]
    report = Verification(segs, False, 2, 0, 0, 0)
    assert v.check_quotes(report, sources) == 1 and report.quotes_total == 2
    assert [m["text"] for s in segs for m in s.misquotes] == ["finance will never arrive"]


def test_a_quotation_is_looked_for_in_the_sources_cited_for_it_and_in_headings(v):
    sources = [src(1, "We oppose the cap.", title="Jane Smith (Selby)", heading="Two child benefit cap"),
               src(2, "The cap must go at once.")]
    # cited to source 1, which does not say it, though source 2 does
    segs = [Segment('She said "the cap must go at once"', [1])]
    report = Verification(segs, False, 1, 0, 0, 0)
    assert v.check_quotes(report, sources) == 1
    # the citation straight after a quotation is the one it is checked against
    for cited_after, not_found in ((2, 0), (1, 1)):
        segs = [Segment('In the "Two child benefit cap" debate she said "the cap must go at once"', status="connective"),
                Segment(" [as recorded]", [cited_after])]
        report = Verification(segs, False, 1, 0, 0, 0)
        assert v.check_quotes(report, sources) == not_found and report.quotes_total == 2
    # with no citation near it, a quotation is looked for in every source
    segs = [Segment('In the "Two child benefit cap" debate she said "the cap must go at once".', status="unsupported")]
    report = Verification(segs, False, 0, 0, 0, 0)
    assert v.check_quotes(report, sources) == 0 and report.quotes_total == 2


def test_a_misquotation_across_segments_is_marked_on_each(v):
    segs = [Segment('He said "wind farms are ', status="connective"), Segment('a blight on us" then.', [1])]
    report = Verification(segs, False, 1, 0, 0, 0)
    assert v.check_quotes(report, [src(1, "Wind farms are welcome.")]) == 1
    assert segs[0].misquotes == [{"start": 8, "end": 24, "text": "wind farms are a blight on us"}]
    assert segs[1].misquotes == [{"start": 0, "end": 15, "text": "wind farms are a blight on us"}]


# ---- what a site passes in --------------------------------------------------------------------------------------


def test_each_sites_source_fits_what_the_checks_ask_of_it(v):
    source: SourceText = src(1, "Costs rose sharply.")
    titled: TitledSource = src(1, "Costs rose sharply.", heading="Rail costs")

    class Bare:  # the two fields are all verify() reads
        n, blocks = 1, ("Costs rose sharply.",)

    block = {"text": "Costs rose", "citations": [{"search_result_index": 0, "cited_text": "costs rose sharply"}]}
    assert v.verify([block], [source]).citations_invalid == v.verify([block], [Bare()]).citations_invalid == 0
    report = Verification([Segment('the "Rail costs" debate was "one of the longest"', [1])], False, 1, 0, 0, 0)
    assert v.check_quotes(report, [titled]) == 1 and report.quotes_total == 1  # two words are a term, not a quotation


def test_the_verifier_needs_its_sites_words_and_rule():
    with pytest.raises(TypeError):
        Verifier(no_records="No records found.")  # type: ignore[call-arg]  # no default for the rule
    with pytest.raises(TypeError):
        Verifier(evidence_notes=EVIDENCE_NOTES_STRICT)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        Verifier("No records found.", EVIDENCE_NOTES_STRICT)  # type: ignore[misc]  # by name only


# ---- the version of the rules (MIGRATION.md 1.4) ----------------------------------------------------------------

OLD_FLAG = {"segments": [{"text": "X said it worked", "status": "cited"},
                         {"text": " (16 September 2025).\n", "status": "unsupported"}],
            "unsupported_segments": 1, "grounded_ratio": 0.432}


def test_every_report_is_stamped_with_the_version_of_the_rules_that_wrote_it(v):
    assert v.rules_version == RULES_VERSION == 1
    answer = v.verify([{"text": "Ministers said "}], []).to_dict()
    assert answer["rules"] == 1 and list(answer)[-1] == "rules"
    assert set(answer) - {"rules"} == {"segments", "markdown", "no_records", "citations_total", "citations_invalid",
                                       "grounded_ratio", "unsupported_segments", "loaded_words", "quotes_total",
                                       "quotes_unverified"}  # today's keys, exactly


def test_an_answer_written_under_the_current_rules_is_left_alone(v):
    for stamp in (v.rules_version, v.rules_version + 1):  # a later one: the package was rolled back
        stamped = {**OLD_FLAG, "rules": stamp}
        assert v.recheck(stamped) is stamped and v.recheck(stamped, curled=True) is stamped


def test_an_answer_with_no_stamp_or_an_older_one_is_judged_again(v):
    for saved in (OLD_FLAG, {**OLD_FLAG, "rules": 0}, {**OLD_FLAG, "rules": None}, {**OLD_FLAG, "rules": "1"},
                  {**OLD_FLAG, "rules": True}):
        out = v.recheck(saved)
        assert [s["status"] for s in out["segments"]] == ["cited", "connective"], saved.get("rules")
        assert out["unsupported_segments"] == 0 and out["grounded_ratio"] == 1.0
        assert out.get("rules") == saved.get("rules")  # judged again is not written again: the stamp is not renewed
        assert saved["segments"][1]["status"] == "unsupported"  # and the saved answer itself is not changed


def test_when_the_rules_change_answers_stamped_before_are_judged_again(v):
    stamped = {**OLD_FLAG, "rules": v.rules_version}
    v.rules_version += 1
    assert v.verify([], []).to_dict()["rules"] == RULES_VERSION + 1
    assert v.recheck(stamped) is not stamped and v.recheck(stamped)["unsupported_segments"] == 0
