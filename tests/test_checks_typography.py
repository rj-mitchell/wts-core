"""Curly quotes in the model's text (wts_core.checks.typography): Where Countries Stand's tests/test_typography.py,
and its end-to-end test of the order the checks run in."""

from __future__ import annotations

from checks_sites import COUNTRIES, MPS, src
from wts_core.checks import curl_answer, curl_event, curl_events, curl_quotes


def test_quotes_and_apostrophes_are_curled():
    assert curl_quotes('"She said \'no\' to them," he wrote.') == "“She said ‘no’ to them,” he wrote."
    assert curl_quotes("Don't touch the States' rights of the '90s.") == "Don’t touch the States’ rights of the ’90s."
    assert curl_quotes('He said: "We\'ll see."') == "He said: “We’ll see.”"
    assert curl_quotes('"\'Nested\'"') == "“‘Nested’”"
    assert curl_quotes('("peace") — "security"') == "(“peace”) — “security”"
    # the asterisks around bold text are not part of the sentence
    assert curl_quotes('**"Sovereignty"** and **Kenya\'s** view') == "**“Sovereignty”** and **Kenya’s** view"
    assert curl_quotes("No quotes here.") == "No quotes here."


def test_addresses_code_and_tags_are_left_alone():
    text = 'See https://example.org/?q="a" and `x = "b"` and <a href="c">it</a>, "said" it.'
    assert curl_quotes(text) == 'See https://example.org/?q="a" and `x = "b"` and <a href="c">it</a>, “said” it.'


def test_a_quotation_across_segments_and_marks_stay_in_place():
    answer = {"markdown": 'Kenya said "climate finance is slow" and it\'s claimed.',
              "segments": [{"text": 'Kenya said "climate ', "status": "connective"},
                           {"text": 'finance is slow"', "status": "cited", "sources": [1]},
                           {"text": " and it's claimed.", "status": "unsupported",
                            "loaded": [{"start": 10, "end": 17, "word": "claimed"}]}]}
    out = curl_answer(answer)
    assert [s["text"] for s in out["segments"]] == ["Kenya said “climate ", "finance is slow”", " and it’s claimed."]
    seg = out["segments"][2]
    assert seg["text"][10:17] == "claimed" and seg["loaded"] == answer["segments"][2]["loaded"]
    assert out["markdown"] == "Kenya said “climate finance is slow” and it’s claimed."
    assert answer["segments"][0]["text"] == 'Kenya said "climate '  # the original is not changed
    assert curl_answer(None) is None and curl_answer({"segments": []}) == {"segments": []}


def test_events_curl_the_interpretation_and_the_briefing_only():
    events = [{"type": "plan", "plan": {"interpretation": 'Read as "climate finance".'}},
              {"type": "sources", "sources": [{"text": 'He said "no".'}]},
              {"type": "final", "answer": {"segments": [{"text": '"Yes."'}]}}]
    out = curl_events(events)
    assert out[0]["plan"]["interpretation"] == "Read as “climate finance”."
    assert out[1] == events[1]  # the record is quoted as it was printed
    assert out[2]["answer"]["segments"][0]["text"] == "“Yes.”"


# ---- from Where Countries Stand's tests/test_pipeline.py --------------------------------------------------------


def test_briefings_are_written_with_curly_quotes():
    quote = "Kenya says climate finance for adaptation is too slow."
    blocks = [{"text": "Kenya's delegate said \""},
              {"text": quote[:40], "citations": [{"search_result_index": 0, "cited_text": quote, "source": "x"}]},
              {"text": "\" in 2023."}]
    final = COUNTRIES.check(blocks, [src(1, quote)])
    text = "".join(s["text"] for s in final["segments"])
    assert text.startswith("Kenya’s delegate said “") and "”" in text and '"' not in text and "'" not in text
    assert final["quotes_total"] == 1  # the quotation was checked before its marks were curled
    assert final["rules"] == 1  # and the stamp of the rules is kept
    assert '"' in "".join(s["text"] for s in MPS.check(blocks, [src(1, quote)])["segments"])  # only where turned on


# ---- cases no site tests ----------------------------------------------------------------------------------------


def test_an_event_with_nothing_to_curl_comes_back_as_it_is():
    for event in ({"type": "text", "text": 'He said "no".'}, {"type": "final", "answer": None, "note": '"x"'},
                  {"type": "plan", "plan": {"interpretation": ""}}, {"type": "plan"}, {"answer": {}}, {}):
        assert curl_event(event) is event
    final = {"type": "final", "answer": {"segments": [{"text": "it's"}, {"status": "connective"}], "rules": 1},
             "briefing_id": "abc"}
    out = curl_event(final)
    assert out == {"type": "final", "briefing_id": "abc",
                   "answer": {"segments": [{"text": "it’s"}, {"status": "connective"}], "rules": 1}}
    assert out["answer"]["segments"][1] is final["answer"]["segments"][1]  # a segment with no text is not rebuilt
