"""The scripted model and the recording format: the fakes pass the same contract as the real adapter."""

from __future__ import annotations

import json

import pytest

from wts_core.events import Block, Citation, CitationDelta, Completed, TextDelta
from wts_core.ports import Document, ModelClient, ModelRequest, Usage
from wts_core.testing.contracts import ModelClientContract, Reading
from wts_core.testing.models import (
    RECORDING_VERSION,
    ScriptedModel,
    load_documents,
    load_header,
    load_stream,
    record_stream,
    recorded,
)

REAL = ("real_cited_briefing", "real_nothing_relevant")
SYNTHETIC = ("cited_briefing", "uncited_claim", "refusal", "max_tokens")
DONE = Completed((Block("Agreed.", (Citation(0, "The Cabinet agreed."),)),), "a-model", "end_turn",
                 Usage(input_uncached=10, output=3))
SCRIPT = [CitationDelta(0, "The Cabinet agreed."), TextDelta("Agr"), TextDelta("eed."), DONE]
REQUEST = ModelRequest(model="a-model", instructions="Use only the sources.", question="What was agreed?",
                       documents=(Document(1, "Minutes", "https://example.org/1", ("The Cabinet agreed.",)),))


class TestScriptedModel(ModelClientContract):
    @pytest.fixture
    def model(self):
        def make(script, structured):
            scripted = ScriptedModel(script, structured=structured)
            return scripted, lambda: scripted.closed > 0

        return make


def test_it_replays_its_script_every_time_and_records_every_request():
    model: ModelClient = ScriptedModel(SCRIPT)
    assert isinstance(model, ScriptedModel)
    other = ModelRequest(model="another", instructions="i", question="q")
    assert list(model.stream(REQUEST)) == SCRIPT and list(model.stream(other)) == SCRIPT
    assert model.requests == [REQUEST, other] and model.started == 2 and model.closed == 0


def test_a_recording_is_replayed_from_its_file():
    model = ScriptedModel(recorded("real_cited_briefing"))
    events = list(model.stream(REQUEST))
    assert len(events) == 46 and isinstance(events[-1], Completed)
    assert events[-1].usage == Usage(input_uncached=701, cache_write=946, cache_read=0, output=548)


def test_a_reader_who_leaves_is_counted():
    model = ScriptedModel(SCRIPT)
    events = model.stream(REQUEST)
    next(events)
    events.close()
    assert model.closed == 1 and model.started == 1
    list(model.stream(REQUEST))
    assert model.closed == 1  # a stream read to its end was not closed early


@pytest.mark.parametrize("script", [[], SCRIPT[:-1], [DONE, TextDelta("late")], [DONE, DONE]])
def test_a_script_must_end_with_its_one_completed(script):
    with pytest.raises(ValueError, match="exactly one Completed, last"):
        ScriptedModel(script)


def test_a_model_that_fails_part_way_says_what_it_had_and_then_raises():
    model = ScriptedModel(SCRIPT[:-1], error=TimeoutError("the connection died"))
    events = model.stream(REQUEST)
    assert [next(events), next(events), next(events)] == SCRIPT[:-1]
    with pytest.raises(TimeoutError, match="connection died"):
        next(events)
    assert model.closed == 0
    with pytest.raises(ValueError, match="no Completed"):
        ScriptedModel(SCRIPT, error=TimeoutError())


def test_a_question_gets_the_prepared_answer_and_the_request_is_kept():
    usage = Usage(input_uncached=32, cache_write=608, output=110)
    model = ScriptedModel(SCRIPT, structured={"search_text": "food waste", "wants_votes": True},
                          structured_usage=usage)
    reading, cost = model.structured(REQUEST, Reading)
    assert (reading.search_text, reading.wants_votes, cost) == ("food waste", True, usage)
    assert model.structured_requests == [(REQUEST, Reading)] and model.requests == []
    ready = Reading("already made")
    assert ScriptedModel(SCRIPT, structured=ready).structured(REQUEST, Reading)[0] is ready


def test_a_model_with_no_prepared_answer_fails_as_the_real_one_does_on_a_refusal():
    """So a site's fall-back to its offline rules can be tested."""
    with pytest.raises(RuntimeError, match=r"query parser returned no output \(stop_reason=refusal\)"):
        ScriptedModel(SCRIPT).structured(REQUEST, Reading)


# --------------------------------------------------------------------------- the recording format


def test_a_stream_comes_back_from_its_file_as_it_went_in(tmp_path):
    path = record_stream(tmp_path / "deep" / "one.jsonl", SCRIPT, documents=REQUEST.documents, site="councils")
    assert load_stream(path) == SCRIPT
    assert load_header(path) == {"recording": RECORDING_VERSION, "documents": 1, "site": "councils", "sources": [
        {"title": "Minutes", "source": "https://example.org/1", "passages": ["The Cabinet agreed."]}]}
    assert load_documents(path) == REQUEST.documents
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line.get("event") for line in lines] == [None, "citation", "text", "text", "completed"]
    assert lines[1] == {"event": "citation", "document": 0, "quoted": "The Cabinet agreed."}
    assert lines[-1]["usage"] == {"input_uncached": 10, "cache_write": 0, "cache_read": 0, "output": 3}


def test_a_recording_may_say_only_how_many_documents_there_were_or_nothing(tmp_path):
    counted = record_stream(tmp_path / "counted.jsonl", SCRIPT, documents=2)
    assert [d.number for d in load_documents(counted)] == [1, 2] and load_documents(counted)[0].passages
    bare = tmp_path / "bare.jsonl"
    bare.write_text("\n".join(counted.read_text().splitlines()[1:]) + "\n\n")
    assert load_header(bare) == {} and load_documents(bare) == () and load_stream(bare) == SCRIPT


def test_a_line_that_is_not_a_model_event_is_an_error(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"event": "final", "answer": {}}\n')
    with pytest.raises(ValueError, match="not a model event"):
        load_stream(path)


def test_words_outside_ascii_are_kept_as_they_are(tmp_path):
    script = [TextDelta("the costs of—(a) “implementation”"), Completed((Block("the costs of—(a) “implementation”"),),
                                                                        "m", "end_turn", Usage())]
    path = record_stream(tmp_path / "x.jsonl", script)
    assert "—(a) “implementation”" in path.read_text(encoding="utf-8") and load_stream(path) == script


def test_an_unknown_recording_names_the_ones_there_are():
    with pytest.raises(FileNotFoundError, match="cited_briefing.*real_cited_briefing"):
        recorded("nothing_of_the_kind")


@pytest.mark.parametrize("name", [*REAL, *SYNTHETIC])
def test_every_recording_that_ships_is_well_formed_and_says_whether_it_is_real(name):
    path = recorded(name)
    header, events, documents = load_header(path), load_stream(path), load_documents(path)
    assert header["recording"] == 1 and header["synthetic"] is (name in SYNTHETIC)
    assert len(documents) == header["documents"] == 3
    done = events[-1]
    assert isinstance(done, Completed)
    # every quotation is, word for word, in the document it names: what the checks will verify
    for citation in [c for b in done.blocks for c in b.citations]:
        assert citation.quoted in documents[citation.document].passages
    if name in REAL:
        assert header["recorded"] == "2026-11-13" and header["instructions"] and header["question"]
        assert done.model == header["requested_model"] and done.stop_reason == "end_turn"


def test_the_real_recordings_show_the_order_the_api_sends():
    """A citation arrives before the text it supports, and the instructions are written to the prompt cache by the
    first request and read from it by the second."""
    events = load_stream(recorded("real_cited_briefing"))
    first_citation = next(i for i, e in enumerate(events) if isinstance(e, CitationDelta))
    done = events[-1]
    cited = next(b for b in done.blocks if b.citations)
    text_so_far = "".join(e.text for e in events[:first_citation] if isinstance(e, TextDelta))
    assert text_so_far == done.blocks[0].text and cited.text not in text_so_far
    assert all(len(b.citations) <= 1 for b in done.blocks)
    assert [e for e in events if isinstance(e, CitationDelta)] == \
        [CitationDelta(c.document, c.quoted) for b in done.blocks for c in b.citations]
    nothing = load_stream(recorded("real_nothing_relevant"))[-1]
    assert nothing.blocks == (Block("The sources provided contain no relevant records."),)
    assert (done.usage.cache_write, nothing.usage.cache_read) == (946, 946)


def test_the_recorded_structured_call_fits_the_schema_that_was_sent():
    raw = json.loads(recorded("real_cited_briefing").with_name("real_structured.json").read_text())
    assert raw["synthetic"] is False and raw["recorded"] == "2026-11-13"
    assert set(raw["parsed"]) == set(raw["schema"]["properties"]) == set(raw["schema"]["required"])
    assert raw["parsed"]["wants_votes"] is True and raw["parsed"]["councils"] == ["Northbridge"]
    assert Usage(**raw["usage"]) == Usage(input_uncached=32, cache_write=608, cache_read=0, output=110)
