"""The Anthropic client: the request it sends, the events it gives back, and that both are the three sites' own.

The SDK is faked, as in the sites' tests: a client whose ``messages.stream`` returns a context manager that yields
``content_block_delta`` events and a final message. No request is ever sent.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import pytest

from adapters_sites import SITES, site_file
from wts_core.adapters import has_model, model_client
from wts_core.adapters.anthropic import (
    BASE_URL,
    FALLBACK_BETA,
    KEY_FILE,
    AnthropicClient,
    api_key,
    base_url,
    has_credentials,
    search_result,
)
from wts_core.events import Block, Citation, CitationDelta, Completed, TextDelta, blocks_as_today, to_reader
from wts_core.ports import ModelClient, ModelRequest, Usage
from wts_core.settings import Settings, SettingsError, Site
from wts_core.testing.contracts import ANSWERS, ModelClientContract
from wts_core.testing.models import Answered, load_documents, load_stream, recorded

MODEL = "briefing-model"


# The SDK, faked


def sdk_usage(usage: Usage) -> NS:
    """Token counts as the SDK reports them: input_tokens leaves the cache writes out."""
    return NS(input_tokens=usage.input_uncached, output_tokens=usage.output,
              cache_read_input_tokens=usage.cache_read, cache_creation_input_tokens=usage.cache_write)


class FakeStream:
    """What ``client.messages.stream(...)`` returns: a context manager over the SDK's events, in the shapes the
    SDK yields them, built from a script of model events."""

    def __init__(self, script, thinking: bool = False):
        self.script = list(script)
        self.done = self.script[-1]
        self.thinking = thinking
        self.entered = self.closed = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def __iter__(self):
        yield NS(type="message_start", message=NS(id="msg_1"))
        if self.thinking:
            yield NS(type="content_block_start", index=0, content_block=NS(type="thinking", thinking=""))
            yield NS(type="content_block_delta", index=0, delta=NS(type="thinking_delta", thinking="Let me see."))
            yield NS(type="content_block_delta", index=0, delta=NS(type="signature_delta", signature="sig"))
            yield NS(type="content_block_stop", index=0)
        yield NS(type="content_block_start", index=1, content_block=NS(type="text", text="", citations=[]))
        for event in self.script[:-1]:
            if isinstance(event, TextDelta):
                yield NS(type="content_block_delta", index=1, delta=NS(type="text_delta", text=event.text))
                yield NS(type="text", text=event.text, snapshot="")  # the SDK's own helper event: not read
            else:
                citation = NS(type="search_result_location", cited_text=event.quoted,
                              search_result_index=event.document, source="https://example.org/x", title="A source",
                              start_block_index=0, end_block_index=1)
                yield NS(type="content_block_delta", index=1, delta=NS(type="citations_delta", citation=citation))
        yield NS(type="content_block_stop", index=1)
        yield NS(type="message_delta", delta=NS(stop_reason=self.done.stop_reason), usage=NS(output_tokens=1))
        yield NS(type="message_stop")

    def get_final_message(self):
        content = [NS(type="thinking", thinking="", signature="sig")] if self.thinking else []
        content += [NS(type="text", text=b.text,
                       citations=[NS(type="search_result_location", cited_text=c.quoted,
                                     search_result_index=c.document, source="https://example.org/x")
                                  for c in b.citations] or None)
                    for b in self.done.blocks]
        return NS(content=content, stop_reason=self.done.stop_reason, model=self.done.model,
                  usage=sdk_usage(self.done.usage))


class FakeSDK:
    """The SDK's client: records every call, and answers a briefing with the script and a question with ``parsed``."""

    def __init__(self, script, parsed: Any = None, refuse_fallbacks: Exception | None = None, thinking=False,
                 parse_stop_reason: str = "end_turn", parse_usage: Any = None):
        self.script, self.parsed, self.thinking = script, parsed, thinking
        self.parse_usage = parse_usage or NS(input_tokens=900, output_tokens=60, cache_read_input_tokens=700,
                                             cache_creation_input_tokens=None)
        self.refuse_fallbacks = refuse_fallbacks
        self.parse_stop_reason = parse_stop_reason
        self.calls: list[dict[str, Any]] = []
        self.parse_calls: list[dict[str, Any]] = []
        self.streams: list[FakeStream] = []
        self.beta = NS(messages=NS(stream=self._beta_stream))
        self.messages = NS(stream=self._stream, parse=self._parse)

    def _beta_stream(self, **kw):
        self.calls.append({"endpoint": "beta", **kw})
        if self.refuse_fallbacks is not None:
            raise self.refuse_fallbacks
        return self._open()

    def _stream(self, **kw):
        self.calls.append({"endpoint": "messages", **kw})
        return self._open()

    def _open(self):
        self.streams.append(FakeStream(self.script, self.thinking))
        return self.streams[-1]

    def _parse(self, **kw):
        self.parse_calls.append(kw)
        schema = kw["output_format"]
        parsed = None if self.parsed is None else schema.model_validate(self.parsed)
        return NS(stop_reason=self.parse_stop_reason, parsed_output=parsed, usage=self.parse_usage)


def client_with(sdk: FakeSDK) -> AnthropicClient:
    return AnthropicClient("sk-ant-test", base_url=BASE_URL, client=sdk)


DOCS = load_documents(recorded("cited_briefing"))
SCRIPT = load_stream(recorded("cited_briefing"))


def request(**changes: Any) -> ModelRequest:
    fields: dict[str, Any] = {"model": MODEL, "instructions": "Use ONLY the sources.",
                              "question": "What was decided about waste?", "documents": DOCS, "max_tokens": 16000,
                              "effort": "medium"}
    return ModelRequest(**{**fields, **changes})


# The contract every adapter passes


class TestAnthropicClient(ModelClientContract):
    @pytest.fixture
    def model(self):
        def make(script, structured):
            if isinstance(structured, Answered):
                # what the API itself answers: through the real SDK, over a transport that answers from memory
                return over_the_real_sdk(TheApi(structured)), lambda: True
            sdk = FakeSDK(script, parsed=structured)
            return client_with(sdk), lambda: bool(sdk.streams) and all(s.closed for s in sdk.streams)

        return make


def test_it_is_a_model_client():
    client: ModelClient = client_with(FakeSDK(SCRIPT))
    assert client.provider == "anthropic"
    assert client.supports == {"caching", "long_cache", "fallbacks", "effort", "citations"}


# The request


def test_the_model_only_ever_sees_the_sources_as_search_results_and_the_instructions():
    sdk = FakeSDK(SCRIPT)
    list(client_with(sdk).stream(request()))
    (call,) = sdk.calls
    blocks = call["messages"][0]["content"]
    assert call["messages"][0]["role"] == "user" and len(call["messages"]) == 1
    assert [b["type"] for b in blocks[:-1]] == ["search_result"] * len(DOCS)
    assert blocks[-1] == {"type": "text", "text": "What was decided about waste?"}
    assert blocks[0] == {"type": "search_result", "source": DOCS[0].source, "title": DOCS[0].title,
                         "content": [{"type": "text", "text": p} for p in DOCS[0].passages],
                         "citations": {"enabled": True}}
    assert list(blocks[0]) == ["type", "source", "title", "content", "citations"]  # the sites' order of keys
    system = call["system"][0]
    assert call["system"] == [{"type": "text", "text": "Use ONLY the sources.", "cache_control": {"type": "ephemeral"}}]
    assert system["cache_control"] == {"type": "ephemeral"}  # the shared instructions are cached
    assert call["fallbacks"] == "default" and call["betas"] == [FALLBACK_BETA] and call["endpoint"] == "beta"
    assert call["model"] == MODEL and call["max_tokens"] == 16000 and call["output_config"] == {"effort": "medium"}
    # nothing else: no thinking, no sampling parameters, no tools
    assert set(call) == {"endpoint", "model", "max_tokens", "system", "messages", "output_config", "betas",
                         "fallbacks"}


def test_a_request_without_fallbacks_uses_the_ordinary_endpoint():
    sdk = FakeSDK(SCRIPT)
    list(client_with(sdk).stream(request(fallbacks=False)))
    (call,) = sdk.calls
    assert call["endpoint"] == "messages" and "betas" not in call and "fallbacks" not in call


@pytest.mark.parametrize("cache, system", [
    ("short", [{"type": "text", "text": "I", "cache_control": {"type": "ephemeral"}}]),
    ("long", [{"type": "text", "text": "I", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]),
    ("off", "I"),
])
def test_how_the_instructions_are_cached_is_the_requests_to_say(cache, system):
    sdk = FakeSDK(SCRIPT, parsed={"search_text": "x"})
    client = client_with(sdk)
    list(client.stream(request(instructions="I", cache_instructions=cache)))
    client.structured(request(instructions="I", cache_instructions=cache, documents=()), Reading)
    assert sdk.calls[0]["system"] == system and sdk.parse_calls[0]["system"] == system


def test_the_long_cache_lifetime_is_one_the_installed_sdk_documents():
    from anthropic.types import CacheControlEphemeralParam

    assert "1h" in str(CacheControlEphemeralParam.__annotations__["ttl"])


def test_an_unknown_cache_setting_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="cache_instructions"):
        list(client_with(FakeSDK(SCRIPT)).stream(request(cache_instructions="forever")))


def test_no_effort_sends_no_output_config():
    sdk = FakeSDK(SCRIPT)
    list(client_with(sdk).stream(request(effort=None)))
    assert "output_config" not in sdk.calls[0]


# The events


def test_text_and_citations_arrive_as_they_are_written_then_the_whole_message():
    events = list(client_with(FakeSDK(SCRIPT)).stream(request()))
    assert events == SCRIPT  # the fake SDK says the recorded stream; the adapter gives the same events back
    done = events[-1]
    assert isinstance(done, Completed) and done.model == "synthetic-model" and done.stop_reason == "end_turn"
    assert done.blocks[1] == Block(DOCS[0].passages[0], (Citation(0, DOCS[0].passages[0]),))
    assert done.blocks[0].citations == ()
    assert events[0] == TextDelta("**Collections**\n\n- In Northbridge,")
    assert CitationDelta(0, DOCS[0].passages[0]) in events


def test_usage_is_counted_as_the_sites_count_it():
    """The SDK's input_tokens leaves cache writes out; the sites' stored form includes them."""
    script = [*SCRIPT[:-1], Completed((), MODEL, "end_turn", Usage(input_uncached=1000, cache_write=300,
                                                                  cache_read=2000, output=200))]
    done = list(client_with(FakeSDK(script)).stream(request()))[-1]
    assert done.usage == Usage(input_uncached=1000, cache_write=300, cache_read=2000, output=200)
    assert done.usage.as_stored() == {"input_tokens": 1300, "output_tokens": 200, "cache_read_tokens": 2000,
                                      "cache_write_tokens": 300}


def test_counts_the_sdk_leaves_empty_are_nought():
    sdk = FakeSDK(SCRIPT)
    client = client_with(sdk)
    stream = FakeStream(SCRIPT)
    message = stream.get_final_message()
    message.usage = NS(input_tokens=10, output_tokens=None)  # no cache counts at all
    stream.get_final_message = lambda: message
    sdk._open = lambda: stream
    assert list(client.stream(request()))[-1].usage == Usage(input_uncached=10)
    message.usage = None
    assert list(client.stream(request()))[-1].usage == Usage()


def test_thinking_is_never_passed_on():
    events = list(client_with(FakeSDK(SCRIPT, thinking=True)).stream(request()))
    assert events == SCRIPT


def test_a_refusal_is_a_finished_message_with_nothing_in_it():
    script = load_stream(recorded("refusal"))
    events = list(client_with(FakeSDK(script)).stream(request()))
    assert events == [Completed((), "synthetic-model", "refusal", script[-1].usage)]


def test_a_briefing_cut_off_at_the_limit_says_so():
    script = load_stream(recorded("max_tokens"))
    done = list(client_with(FakeSDK(script)).stream(request()))[-1]
    assert done.stop_reason == "max_tokens" and done.blocks[-1].text.endswith("fortn")


def test_a_reader_who_leaves_closes_the_sdks_stream():
    sdk = FakeSDK(SCRIPT)
    events = client_with(sdk).stream(request())
    assert next(events) == SCRIPT[0]
    assert sdk.streams[0].entered and not sdk.streams[0].closed
    events.close()
    assert sdk.streams[0].closed


# The fallback beta


def bad_request(message: str) -> Exception:
    import anthropic
    import httpx2

    response = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    return anthropic.BadRequestError(message, response=response, body=None)


def test_the_fallback_beta_is_dropped_when_refused_and_not_asked_for_again(caplog):
    sdk = FakeSDK(SCRIPT, refuse_fallbacks=bad_request("fallbacks: Extra inputs are not permitted"))
    client = client_with(sdk)
    assert list(client.stream(request())) == SCRIPT
    assert [c["endpoint"] for c in sdk.calls] == ["beta", "messages"]
    assert "fallbacks" not in sdk.calls[1] and "betas" not in sdk.calls[1]
    assert {k: v for k, v in sdk.calls[0].items() if k not in ("endpoint", "betas", "fallbacks")} == \
        {k: v for k, v in sdk.calls[1].items() if k != "endpoint"}  # the same request, without the beta
    assert client.fallbacks_refused and "fallbacks rejected" in caplog.text
    # remembered for the life of the client: the next briefing makes one request, not a refused one first
    assert list(client.stream(request())) == SCRIPT
    assert [c["endpoint"] for c in sdk.calls] == ["beta", "messages", "messages"]


def test_another_bad_request_is_not_mistaken_for_the_beta_being_refused():
    sdk = FakeSDK(SCRIPT, refuse_fallbacks=bad_request("max_tokens: must be at most 128000"))
    client = client_with(sdk)
    with pytest.raises(Exception, match="max_tokens"):
        list(client.stream(request()))
    assert len(sdk.calls) == 1 and not client.fallbacks_refused


def test_an_error_that_is_not_a_bad_request_is_raised_as_it_is():
    sdk = FakeSDK(SCRIPT, refuse_fallbacks=RuntimeError("the fallback service is down"))
    with pytest.raises(RuntimeError, match="fallback service"):
        list(client_with(sdk).stream(request()))
    assert len(sdk.calls) == 1


# Reading a question into a schema


class Reading:
    def __init__(self, search_text: str, wants_votes: bool = False):
        self.search_text, self.wants_votes = search_text, wants_votes

    @classmethod
    def model_json_schema(cls) -> dict[str, Any]:
        return {"type": "object"}

    @classmethod
    def model_validate(cls, obj: Any) -> Reading:
        return cls(**obj)


def test_a_question_is_read_with_the_sites_parse_call():
    sdk = FakeSDK(SCRIPT, parsed={"search_text": "bin collections"})
    ask = ModelRequest(model="parse-model", instructions="Read the question.", question="Question: bins in Leeds?",
                       max_tokens=2000, effort="low")
    reading, usage = client_with(sdk).structured(ask, Reading)
    assert reading.search_text == "bin collections"
    assert sdk.parse_calls == [{
        "model": "parse-model", "max_tokens": 2000,
        "system": [{"type": "text", "text": "Read the question.", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "Question: bins in Leeds?"}],
        "output_config": {"effort": "low"}, "output_format": Reading}]
    assert sdk.calls == []  # one call, not streamed, and never the fallback beta
    assert usage == Usage(input_uncached=900, cache_read=700, output=60)


def test_the_real_sdk_accepts_a_pydantic_schema_in_that_call():
    """The call is made on the real SDK's ``messages.parse`` with the network cut off: it must get as far as
    sending, which shows that every argument is one the installed SDK takes."""
    import anthropic
    import httpx2
    from pydantic import BaseModel

    class Parsed(BaseModel):
        search_text: str

    sent: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        sent.append(req)
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "parse-model", "stop_reason": "end_turn",
            "stop_sequence": None, "content": [{"type": "text", "text": '{"search_text": "bins"}'}],
            "usage": {"input_tokens": 12, "output_tokens": 5}})

    sdk = anthropic.Anthropic(api_key="sk-ant-test", base_url=BASE_URL, max_retries=0,
                              http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    ask = ModelRequest(model="parse-model", instructions="Read.", question="Question: bins?", max_tokens=2000,
                       effort="low")
    reading, usage = AnthropicClient("sk-ant-test", base_url=BASE_URL, client=sdk).structured(ask, Parsed)
    assert reading == Parsed(search_text="bins") and usage == Usage(input_uncached=12, output=5)
    import json

    body = json.loads(sent[0].content)
    assert body["output_config"]["effort"] == "low" and body["output_config"]["format"]["type"] == "json_schema"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"} and body["max_tokens"] == 2000


def test_the_real_sdk_accepts_the_briefing_call_and_its_stream_is_read():
    """The same for a briefing: the real SDK's ``beta.messages.stream`` is given the adapter's call, and answers
    from a canned server-sent stream in the API's own format, citations included."""
    import json

    import anthropic
    import httpx2

    quote = DOCS[0].passages[0]
    citation = {"type": "search_result_location", "cited_text": quote, "search_result_index": 0,
                "source": DOCS[0].source, "title": DOCS[0].title, "start_block_index": 0, "end_block_index": 1}
    wire = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": MODEL, "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 1840, "output_tokens": 1, "cache_read_input_tokens": 2890,
                      "cache_creation_input_tokens": 0}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": "The Cabinet decided: "}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("content_block_start", {"type": "content_block_start", "index": 1,
                                 "content_block": {"type": "text", "text": "", "citations": []}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1,
                                 "delta": {"type": "citations_delta", "citation": citation}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1,
                                 "delta": {"type": "text_delta", "text": quote}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 1}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 57}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    sent: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        sent.append(req)
        body = "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in wire)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())

    sdk = anthropic.Anthropic(api_key="sk-ant-test", base_url=BASE_URL, max_retries=0,
                              http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    events = list(AnthropicClient("sk-ant-test", base_url=BASE_URL, client=sdk).stream(request()))
    assert events == [
        TextDelta("The Cabinet decided: "), CitationDelta(0, quote), TextDelta(quote),
        Completed((Block("The Cabinet decided: "), Block(quote, (Citation(0, quote),))), MODEL, "end_turn",
                  Usage(input_uncached=1840, cache_read=2890, output=57))]
    body = json.loads(sent[0].content)
    assert body["fallbacks"] == "default" and FALLBACK_BETA in sent[0].headers["anthropic-beta"]
    assert body["stream"] is True and body["output_config"] == {"effort": "medium"}
    assert [b["type"] for b in body["messages"][0]["content"]] == ["search_result"] * 3 + ["text"]
    assert body["messages"][0]["content"][0]["citations"] == {"enabled": True}


@pytest.mark.parametrize("stop_reason, parsed", [("refusal", {"search_text": "x"}), ("end_turn", None)])
def test_a_refusal_or_no_output_raises_as_today(stop_reason, parsed):
    sdk = FakeSDK(SCRIPT, parsed=parsed, parse_stop_reason=stop_reason)
    with pytest.raises(RuntimeError, match=rf"query parser returned no output \(stop_reason={stop_reason}\)") as no:
        client_with(sdk).structured(request(documents=()), Reading)
    # Found by Where MPs Stand's adoption: the call was paid for, and its token counts were lost with the bare
    # error, so it was in nobody's spending. The error now carries them (the fake SDK's: 900 in, 700 of them read
    # from the cache, 60 out), as the site's own ``usage_dict`` would have counted them.
    from wts_core.ports import NoStructuredAnswer

    assert isinstance(no.value, NoStructuredAnswer) and no.value.stop_reason == stop_reason
    assert no.value.usage == Usage(input_uncached=900, cache_read=700, output=60)


# What Where MPs Stand's own code recorded for its interests check when the model's answer had nothing parsed in
# it, from that site's recorded golden (tests/golden/interests.json, "an answer with nothing parsed in it"): the
# call was billed, 400 tokens in and 30 out, and the old code counted it. On 0.2.1 the adapter raised a bare error,
# the site could only take the answer as "no matches", and the cost was recorded nowhere.
BILLED_FOR_NOTHING = {"input_tokens": 400, "output_tokens": 30, "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0}


@pytest.mark.parametrize("stop_reason", ["end_turn", "refusal"])
def test_a_call_that_gives_nothing_was_still_billed_and_a_site_can_still_record_what_it_cost(stop_reason, tmp_path):
    """Found by the independent review of Where MPs Stand's adoption. The error carries the usage, and the site
    records it exactly as it would have recorded an answer: the same row, the same cost."""
    from wts_core import usage as core_usage
    from wts_core.ports import NoStructuredAnswer
    from wts_core.state import StateDB
    from wts_core.usage import PriceTable, Spending

    sdk = FakeSDK(SCRIPT, parsed=None, parse_stop_reason=stop_reason, parse_usage=NS(**BILLED_FOR_NOTHING))
    prices = PriceTable.from_settings({"price_input_per_mtok": 1.0, "price_output_per_mtok": 5.0,
                                       "price_cache_read_per_mtok": 0.1, "cache_write_multiplier": 1.25})
    spending = Spending(StateDB(tmp_path / "state.db", migrations=core_usage.migrations()), prices)
    try:  # as a site's pipeline does: its own rules take over, and the reading that failed is paid for all the same
        client_with(sdk).structured(request(documents=()), Reading)
        raise AssertionError("an answer with nothing in it was taken as an answer")
    except NoStructuredAnswer as nothing:
        billed = nothing.usage
        cost = spending.add("interests", "claude-haiku-5-5", billed)
    assert billed == Usage(input_uncached=400, output=30) == Usage.from_mapping(BILLED_FOR_NOTHING)
    assert cost == pytest.approx(400 / 1e6 * 1.0 + 30 / 1e6 * 5.0) and cost > 0
    assert spending.spent_since("2000-01-01T00:00:00+00:00") == pytest.approx(cost)


def test_the_figures_above_are_where_mps_stands_own_golden():
    """Read from the site's checkout where its adoption is there to read; the figures above are a copy."""
    import json

    from adapters_sites import sites_dir

    home = sites_dir()
    places = [home / "wherempsstand" / "tests" / "golden" / "interests.json"] if home else []
    places.append(Path("/home/user/wt/mps-adopt/tests/golden/interests.json"))  # its adoption's own worktree
    golden = next((p for p in places if p.is_file()), None)
    if golden is None:
        pytest.skip("no checkout of Where MPs Stand's adoption with tests/golden/interests.json")
    assert json.loads(golden.read_text())["an answer with nothing parsed in it"]["usage"] == BILLED_FOR_NOTHING


# The real SDK, with the network cut out
#
# The fake above stands where the SDK does, and answers with what the SDK would have parsed. What the SDK really
# does with an answer it cannot parse, the fake cannot say: the independent review of 0.3.0 found it by putting the
# real SDK over a transport that answers from memory. So do these: no network, no key, no model.


class TheApi:
    """The Messages API, answering every request with one message: ``answered``'s text (or no content at all),
    its stop reason and its usage, as the API reports them. Every request it was sent is kept, as it was on the
    wire: its headers and the bytes of its body."""

    def __init__(self, answered: Answered) -> None:
        self.answered, self.sent = answered, []

    def __call__(self, request):
        httpx = the_sdks_httpx()
        self.sent.append((dict(request.headers), request.content))
        usage = self.answered.usage
        return httpx.Response(200, json={
            "id": "msg_x", "type": "message", "role": "assistant", "model": "parse-model",
            "content": [] if self.answered.text is None else [{"type": "text", "text": self.answered.text}],
            "stop_reason": self.answered.stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": usage.input_uncached, "output_tokens": usage.output,
                      "cache_creation_input_tokens": usage.cache_write,
                      "cache_read_input_tokens": usage.cache_read}})


def the_sdks_httpx():
    """The HTTP library the installed SDK is built on: it refuses a transport of any other."""
    try:
        import httpx2 as httpx
    except ImportError:
        import httpx
    return httpx


def real_sdk(api: TheApi):
    anthropic = pytest.importorskip("anthropic")
    httpx = the_sdks_httpx()
    return anthropic.Anthropic(api_key="not-a-key", base_url="http://127.0.0.1:9", max_retries=0,
                               http_client=httpx.Client(transport=httpx.MockTransport(api)))


def over_the_real_sdk(api: TheApi) -> AnthropicClient:
    return AnthropicClient(None, base_url="http://127.0.0.1:9", client=real_sdk(api))


def pydantic_reading():
    """A schema as the sites write theirs: a Pydantic model, with an optional field, a list and a nested model."""
    pydantic = pytest.importorskip("pydantic")

    class Period(pydantic.BaseModel):
        start: str | None = pydantic.Field(None, description="The first day asked about, if any.")
        end: str | None = None

    class ParsedReading(pydantic.BaseModel):
        search_text: str = pydantic.Field(description="What to search for.")
        wants_votes: bool = False
        councils: list[str] = []
        period: Period | None = None

    return ParsedReading


@pytest.mark.parametrize("answer", list(ANSWERS))
def test_over_the_real_sdk_every_answered_call_reaches_the_caller_with_what_it_cost(answer):
    """The review's seven cases, with a schema that is a Pydantic model, as the sites' are. Before, five of them
    raised Pydantic's error from inside the SDK, which had read the response and thrown it away: 400 tokens in
    and 30 out, billed, and in nobody's spending."""
    from wts_core.ports import NoStructuredAnswer

    schema, api = pydantic_reading(), TheApi(ANSWERS[answer])
    client = over_the_real_sdk(api)
    ask = request(documents=(), max_tokens=2000, effort="low")
    if answer == "a sound answer":
        reading, usage = client.structured(ask, schema)
        assert isinstance(reading, schema) and (reading.search_text, reading.wants_votes) == ("bin collections", True)
        assert usage == Usage(input_uncached=400, output=30)
    else:
        with pytest.raises(NoStructuredAnswer) as nothing:
            client.structured(ask, schema)
        assert nothing.value.usage == Usage(input_uncached=400, output=30)
        assert nothing.value.stop_reason == ANSWERS[answer].stop_reason
        assert str(nothing.value).startswith(f"query parser returned no output (stop_reason={nothing.value.stop_reason})")
        # nothing the model wrote is in the error or in what a traceback would print of it: it may be a reader's
        assert nothing.value.__cause__ is None
        assert nothing.value.__context__ is None or nothing.value.__suppress_context__
    assert len(api.sent) == 1  # one call, never a second to make up for the first


@pytest.mark.parametrize("ask", [
    request(documents=(), max_tokens=2000, effort="low"),
    request(documents=(), max_tokens=6000, effort=None),
    request(documents=(), max_tokens=2000, effort="medium", cache_instructions="long"),
    request(documents=(), max_tokens=2000, effort="low", cache_instructions="off"),
])
def test_what_is_sent_to_read_a_question_is_byte_for_byte_what_the_sdks_parse_sends(ask):
    """The adapter fetches the answer with ``messages.create`` so that it holds the response whatever is in it.
    What it sends must be what ``messages.parse`` sent before, to the byte and to the header: the same keywords
    the parity tests hold to each site's own code, given to the SDK's own ``parse`` over the same transport."""
    schema = pydantic_reading()
    answered = ANSWERS["a sound answer"]
    ours, theirs = TheApi(answered), TheApi(answered)
    over_the_real_sdk(ours).structured(ask, schema)
    recorded_by_fake = FakeSDK(SCRIPT, parsed={"search_text": "x"})
    client_with(recorded_by_fake).structured(ask, schema)  # the keywords, as the stand-in for the SDK is given them
    (keywords,) = recorded_by_fake.parse_calls
    real_sdk(theirs).messages.parse(**keywords)
    (our_headers, our_body), (their_headers, their_body) = ours.sent[0], theirs.sent[0]
    assert our_body == their_body and b'"format":{"schema":' in our_body
    assert our_headers == their_headers and our_headers["x-stainless-helper"] == "messages.parse"


class PassesThrough:
    """A wrapper as a tracing library makes one: not the SDK's client, and every call handed on to it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class HasTheSdksMessages:
    """Another client class altogether (as the SDK's own for other platforms are), with the SDK's ``messages``."""

    def __init__(self, inner: Any) -> None:
        self.messages, self.beta = inner.messages, inner.beta


def other_platforms_client(kind: str, api: TheApi) -> Any:
    """A client that is not ``anthropic.Anthropic``: the SDK's own for Bedrock or Vertex, over the same
    transport, or a wrapper round the SDK's client."""
    anthropic = pytest.importorskip("anthropic")
    httpx = the_sdks_httpx()
    http = httpx.Client(transport=httpx.MockTransport(api))
    if kind == "Bedrock's client":
        return anthropic.AnthropicBedrockMantle(aws_region="eu-west-2", api_key="not-a-key", max_retries=0,
                                                http_client=http)
    if kind == "Vertex's client":
        return anthropic.AnthropicVertex(project_id="a-project", region="global", access_token="not-a-token",
                                         max_retries=0, http_client=http)
    wrap = PassesThrough if kind == "a wrapper that passes calls through" else HasTheSdksMessages
    return wrap(real_sdk(api))


OTHER_CLIENTS = ("Bedrock's client", "Vertex's client", "a wrapper that passes calls through",
                 "another class with the SDK's messages")


@pytest.mark.parametrize("kind", OTHER_CLIENTS)
@pytest.mark.parametrize("answer", [name for name in ANSWERS if name != "a sound answer"])
def test_a_failed_reading_keeps_its_cost_whatever_client_made_the_call(kind, answer):
    """Found by the second independent review of 0.3.0: the path that keeps the usage was chosen by asking
    whether the client IS ``anthropic.Anthropic``. The SDK's clients for Bedrock and Vertex are not, nor is a
    wrapper round the SDK's client, so on those every answer that could not be read still lost its cost. It is
    chosen by what the client can do: it has ``messages.create``."""
    anthropic = pytest.importorskip("anthropic")
    from wts_core.ports import NoStructuredAnswer

    api = TheApi(ANSWERS[answer])
    try:
        client = other_platforms_client(kind, api)
    except Exception as exc:  # a platform's own library that is not installed here
        pytest.skip(f"{kind} cannot be made here: {type(exc).__name__}")
    assert not isinstance(client, anthropic.Anthropic)
    with pytest.raises(NoStructuredAnswer) as nothing:
        AnthropicClient(None, base_url="http://127.0.0.1:9", client=client).structured(
            request(documents=(), max_tokens=2000, effort="low"), pydantic_reading())
    assert nothing.value.usage == Usage(input_uncached=400, output=30)
    assert nothing.value.stop_reason == ANSWERS[answer].stop_reason and len(api.sent) == 1


def test_a_stand_in_that_has_only_parse_is_called_as_each_sites_own_code_called_the_sdk():
    """The sites' tests, and this package's parity tests, stand a plain object in for the SDK that has
    ``messages.parse`` and nothing else, and hold its keywords to each site's own call. That road is kept."""
    sdk = FakeSDK(SCRIPT, parsed={"search_text": "x"})
    assert not hasattr(sdk.messages, "create")
    reading, _ = client_with(sdk).structured(request(documents=(), max_tokens=2000, effort="low"), Reading)
    assert reading.search_text == "x" and len(sdk.parse_calls) == 1 and sdk.parse_calls[0]["output_format"] is Reading


# The key, the address, the client


def site(prefix: str = "COUNCILS", root: Path = Path(".")) -> Site:
    return Site(name="Where Councils Stand", package="councils", env_prefix=prefix, root=root)


def settings_for(tmp_path: Path, a_site: Site, **answer: Any) -> Settings:
    return Settings(raw={"answer": answer}, data_dir=tmp_path, config_path=tmp_path / "settings.toml", site=a_site)


@pytest.mark.parametrize("prefix", ["HANSARD", "WCS", "COUNCILS"])
def test_api_key_falls_back_to_the_key_file_in_the_data_folder(tmp_path, prefix):
    a_site = site(prefix)
    settings = settings_for(tmp_path, a_site)
    assert api_key(a_site, settings, {}) is None
    (tmp_path / KEY_FILE).write_text("sk-ant-from-file\n")
    assert api_key(a_site, settings, {}) == "sk-ant-from-file"
    assert api_key(a_site, settings, {"ANTHROPIC_API_KEY": "sk-ant-shared"}) == "sk-ant-shared"
    both = {"ANTHROPIC_API_KEY": "sk-ant-shared", f"{prefix}_ANTHROPIC_API_KEY": "sk-ant-from-env"}
    assert api_key(a_site, settings, both) == "sk-ant-from-env"
    assert api_key(a_site, settings, {f"{prefix}_ANTHROPIC_API_KEY": ""}) == "sk-ant-from-file"  # empty is unset


def test_the_key_is_read_from_the_real_environment_when_none_is_given(tmp_path, monkeypatch):
    monkeypatch.setenv("COUNCILS_ANTHROPIC_API_KEY", "sk-ant-from-env")
    assert api_key(site(), settings_for(tmp_path, site())) == "sk-ant-from-env"


def test_an_empty_key_file_is_no_key(tmp_path):
    (tmp_path / KEY_FILE).write_text("\n")
    assert api_key(site(), settings_for(tmp_path, site()), {}) is None
    assert not has_credentials(site(), settings_for(tmp_path, site()), {})
    assert has_credentials(site(), settings_for(tmp_path, site()), {"ANTHROPIC_AUTH_TOKEN": "token"})
    assert has_credentials(site(), settings_for(tmp_path, site()), {"COUNCILS_ANTHROPIC_API_KEY": "k"})


def test_an_inherited_base_url_is_never_followed(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example.org")
    assert base_url(site(), {"ANTHROPIC_BASE_URL": "https://proxy.example.org"}) == "https://api.anthropic.com"
    assert base_url(site(), {"COUNCILS_ANTHROPIC_BASE_URL": "https://gateway.example.org"}) == \
        "https://gateway.example.org"
    client = model_client(settings_for(tmp_path, site()), site(), {"COUNCILS_ANTHROPIC_API_KEY": "sk-ant-test"})
    assert isinstance(client, AnthropicClient)
    assert str(client.client.base_url).startswith("https://api.anthropic.com")  # the SDK was not left to choose


@pytest.mark.parametrize("prefix", ["HANSARD", "WCS", "COUNCILS"])
def test_model_client_gives_up_on_a_dead_connection(tmp_path, prefix):
    """A stalled connection must not hold a briefing (and its place under the caps) open for ever."""
    a_site = site(prefix)
    client = model_client(settings_for(tmp_path, a_site), a_site, {f"{prefix}_ANTHROPIC_API_KEY": "sk-ant-test"})
    assert isinstance(client, AnthropicClient)
    assert (client.timeout, client.connect, client.max_retries) == (300.0, 10.0, 2)  # the same in every site
    sdk = client.client
    assert sdk.timeout.read == 300.0 and sdk.timeout.connect == 10.0 and sdk.max_retries == 2
    assert str(sdk.base_url).startswith("https://api.anthropic.com")
    assert sdk.api_key == "sk-ant-test"
    assert client.client is sdk  # made once


def test_without_a_key_the_sdks_own_credentials_apply(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-of-the-sdks-own")
    client = model_client(settings_for(tmp_path, site()), site(), {})
    assert isinstance(client, AnthropicClient) and client.api_key is None
    assert client.client.auth_token == "token-of-the-sdks-own"


def test_the_provider_is_a_setting_and_an_unknown_one_names_it(tmp_path):
    assert isinstance(model_client(settings_for(tmp_path, site(), provider="anthropic"), site(), {}), AnthropicClient)
    with pytest.raises(SettingsError, match=r"settings\.toml: \[answer\] provider is 'acme'"):
        model_client(settings_for(tmp_path, site(), provider="acme"), site(), {})


def test_whether_there_is_a_model_is_asked_without_naming_the_provider(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    settings = settings_for(tmp_path, site())
    assert has_model(settings, site(), {}) is False  # no key: the site shows the sources only
    assert has_model(settings, site(), {"COUNCILS_ANTHROPIC_API_KEY": "sk-ant-test"}) is True
    assert has_model(settings, site(), {"ANTHROPIC_AUTH_TOKEN": "token"}) is True
    assert has_model(settings, site(), {"WCS_ANTHROPIC_API_KEY": "another-sites"}) is False
    (tmp_path / KEY_FILE).write_text("sk-ant-from-the-file\n")
    assert has_model(settings, site(), {}) is True
    # the same answer as the provider's own module gives, and the same refusal of a provider there is none for
    assert has_model(settings, site(), {}) == has_credentials(site(), settings, {})
    with pytest.raises(SettingsError, match=r"settings\.toml: \[answer\] provider is 'acme'"):
        has_model(settings_for(tmp_path, site(), provider="acme"), site(), {})


def test_importing_the_adapters_needs_no_sdk():
    import subprocess
    import sys

    code = ("import sys; import wts_core.adapters, wts_core.adapters.anthropic, wts_core.adapters.lancedb, "
            "wts_core.adapters.hashing, wts_core.adapters.fastembed; "
            "print(sorted(m for m in ('anthropic', 'lancedb', 'fastembed', 'numpy', 'pyarrow') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


# The same as each site's own code


def site_code(name: str, relative: str) -> ast.Module:
    return ast.parse(site_file(name, relative).read_text())


def definition(module: ast.Module, name: str) -> str:
    """The source of one top-level function or class of a site's module."""
    node = next(n for n in module.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
    return ast.unparse(node)


def method(module: ast.Module, cls: str, name: str) -> str:
    owner = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return ast.unparse(next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == name))


def site_answerer(name: str) -> tuple[Any, Any]:
    """The site's own ``Answerer`` and ``Source.search_result``, run from its source with stand-ins for its
    instructions (which stay the site's)."""
    import logging

    answer = site_code(name, "rag/answer.py")
    sources = site_code(name, "rag/sources.py")
    space: dict[str, Any] = {"log": logging.getLogger("site"), "FALLBACK_BETA": "server-side-fallback-2026-07-01",
                             "system_prompt": lambda today: "Use ONLY the sources.",
                             "user_instruction": lambda question, *rest: question, "make_client": None}
    code = "\n\n".join(["from __future__ import annotations", "from datetime import date",
                        definition(answer, "cached_system"), definition(answer, "usage_dict"),
                        definition(answer, "_block_to_dict"), definition(answer, "Answerer"),
                        "def search_result(self):\n" + "\n".join(
                            "    " + line for line in method(sources, "Source", "search_result").splitlines()[1:])])
    exec(code, space)  # the sites' own code, read from their checkouts
    return space["Answerer"], space["search_result"]


@pytest.mark.parametrize("name", list(SITES))
def test_the_call_and_the_events_are_the_sites_own(name):
    """The site's ``Answerer.stream`` and the adapter are given the same sources and the same fake SDK: the calls
    they make must be equal, and so must what they yield."""
    answerer, site_search_result = site_answerer(name)
    script = [*SCRIPT[:-1], Completed(SCRIPT[-1].blocks, MODEL, "end_turn",
                                      Usage(input_uncached=1840, cache_write=310, cache_read=2890, output=412))]
    sources = [NS(url=d.source, title=d.title, blocks=list(d.passages)) for d in DOCS]
    for s in sources:
        s.search_result = lambda s=s: site_search_result(s)
        assert s.search_result() == search_result(DOCS[sources.index(s)])
        assert list(s.search_result()) == list(search_result(DOCS[sources.index(s)]))

    theirs_sdk, ours_sdk = FakeSDK(script, thinking=True), FakeSDK(script, thinking=True)
    settings = NS(answer={"model": MODEL, "max_tokens": 16000, "summary_effort": "medium", "use_fallbacks": True})
    theirs = list(answerer(settings, client=theirs_sdk).stream("What was decided about waste?", sources))
    ours = list(client_with(ours_sdk).stream(request()))

    assert ours_sdk.calls == theirs_sdk.calls
    assert [to_reader(e) for e in ours[:-1]] == theirs[:-1]
    final, done = theirs[-1], ours[-1]
    assert (final["type"], final["stop_reason"], final["model"]) == ("final", done.stop_reason, done.model)
    assert final["usage"] == done.usage.as_stored()
    # the site keeps each citation's own `source` (the address), which the package's events do not carry
    assert [{"text": b["text"], "citations": [{**c, "source": None} for c in b["citations"]]}
            for b in final["blocks"]] == blocks_as_today(done)


@pytest.mark.parametrize("name", list(SITES))
def test_the_refused_beta_is_retried_as_the_site_retries_it(name):
    answerer, _ = site_answerer(name)
    refusal = bad_request("fallbacks: Extra inputs are not permitted")
    theirs_sdk, ours_sdk = FakeSDK(SCRIPT, refuse_fallbacks=refusal), FakeSDK(SCRIPT, refuse_fallbacks=refusal)
    settings = NS(answer={"model": MODEL, "max_tokens": 16000, "summary_effort": "medium"})
    sources = [NS(search_result=lambda d=d: search_result(d)) for d in DOCS]
    theirs = list(answerer(settings, client=theirs_sdk).stream("What was decided about waste?", sources))
    ours = list(client_with(ours_sdk).stream(request()))
    assert ours_sdk.calls == theirs_sdk.calls and len(theirs) == len(ours)


@pytest.mark.parametrize("name", list(SITES))
def test_the_parse_call_is_the_one_each_site_makes(name):
    """Each site's ``parse_with_model`` is read, not run (it goes on to build the site's own plan): the keywords of
    its ``client.messages.parse(...)`` call are the adapter's."""
    module = site_code(name, "rag/query_parse.py")
    calls = [n for n in ast.walk(module) if isinstance(n, ast.Call)
             and ast.unparse(n.func) == "client.messages.parse"]
    assert len(calls) == 1
    sdk = FakeSDK(SCRIPT, parsed={"search_text": "x"})
    client_with(sdk).structured(request(documents=(), max_tokens=2000, effort="low"), Reading)
    assert sorted(k.arg for k in calls[0].keywords) == sorted(sdk.parse_calls[0])
    keywords = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
    assert keywords["max_tokens"] == "2000" and keywords["system"].startswith("cached_system(")
    assert keywords["messages"].startswith("[{'role': 'user', 'content': f")  # one user message, a plain string
    assert keywords["output_config"].startswith("{'effort': settings.answer.get('query_parse_effort'")
