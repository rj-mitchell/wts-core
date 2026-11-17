"""Swapping parts, third of three: the template adapter for a second provider.

``wts_core.adapters.skeleton_provider`` is not a client for any real service and is wired into no site. It is here
to show that the model interface can be met over another provider's wire, and what a provider without citations
means for the checks. The provider is played by an ``httpx`` transport that answers from the recorded streams that
ship with the package, written out in the provider's own (invented) shape. No request leaves the machine.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

httpx = pytest.importorskip("httpx")

from checks_sites import COUNCILS as CHECKS  # noqa: E402
from wts_core import adapters  # noqa: E402
from wts_core.adapters.skeleton_provider import FINISH, SkeletonProviderClient, document, usage_of  # noqa: E402
from wts_core.eval import checked  # noqa: E402
from wts_core.events import Block, Citation, CitationDelta, Completed, TextDelta  # noqa: E402
from wts_core.ports import ModelClient, ModelRequest, NoStructuredAnswer, Usage  # noqa: E402
from wts_core.testing.contracts import ModelClientContract, Reading  # noqa: E402
from wts_core.testing.models import Answered, ScriptedModel, load_documents, load_stream, recorded  # noqa: E402

BASE = "https://provider.invalid"
FINISHED = {ours: theirs for theirs, ours in FINISH.items()}  # the family's word -> the provider's


class Wire(httpx.SyncByteStream):
    """The provider's streamed answer: lines of ``data: {…}``, and a note of whether the connection was closed."""

    def __init__(self, lines: list[dict[str, Any]]) -> None:
        self.lines, self.closed = lines, False

    def __iter__(self) -> Iterator[bytes]:
        for line in self.lines:
            yield f"data: {json.dumps(line)}\n\n".encode()

    def close(self) -> None:
        self.closed = True


class Provider:
    """The second provider, answering from a script of model events (a recorded stream) in its own shape. One
    that ``gives_citations`` sends the document and the quoted words; one that does not sends the text alone."""

    def __init__(self, script: list[Any], structured: Any = None, *, gives_citations: bool, status: int = 200) -> None:
        self.script, self.structured_answer = list(script), structured
        self.gives_citations, self.status = gives_citations, status
        self.requests: list[dict[str, Any]] = []
        self.wires: list[Wire] = []

    def _lines(self) -> list[dict[str, Any]]:
        lines: list[dict[str, Any]] = []
        for event in self.script:
            if isinstance(event, TextDelta):
                lines.append({"type": "text", "text": event.text})
            elif isinstance(event, CitationDelta) and self.gives_citations:
                lines.append({"type": "citation", "document": event.document, "quote": event.quoted})
            elif isinstance(event, Completed):
                lines.append({
                    "type": "done", "model": event.model, "finish": FINISHED.get(event.stop_reason or "", "stop"),
                    "output": [{"text": b.text, **({"citations": [{"document": c.document, "quote": c.quoted}
                                                                  for c in b.citations]}
                                                   if self.gives_citations else {})} for b in event.blocks],
                    # as this provider counts: its prompt tokens include those read from its cache
                    "usage": {"prompt_tokens": event.usage.input_uncached + event.usage.cache_read,
                              "cached_prompt_tokens": event.usage.cache_read,
                              "completion_tokens": event.usage.output}})
        return lines

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append({"url": str(request.url), "auth": request.headers.get("authorization"), **body})
        if self.status >= 400:
            return httpx.Response(self.status, json={"error": "the question was: " + body["input"][-1]["text"]})
        if "response_schema" in body:
            answer = self.structured_answer
            if not isinstance(answer, Answered):  # what a question is read into, or None: said as this provider would
                answer = Answered(json.dumps(answer), "end_turn") if answer else Answered(None, "refusal")
            return httpx.Response(200, json={
                "output_text": answer.text, "finish": FINISHED.get(answer.stop_reason, "stop"),
                "usage": {"prompt_tokens": answer.usage.input_uncached + answer.usage.cache_read,
                          "cached_prompt_tokens": answer.usage.cache_read,
                          "completion_tokens": answer.usage.output}})
        self.wires.append(Wire(self._lines()))
        return httpx.Response(200, stream=self.wires[-1])


def client_for(provider: Provider) -> SkeletonProviderClient:
    return SkeletonProviderClient("key-for-the-test", base_url=BASE, gives_citations=provider.gives_citations,
                                  client=httpx.Client(transport=httpx.MockTransport(provider),
                                                      headers={"Authorization": "Bearer key-for-the-test"}))


DOCS = load_documents(recorded("cited_briefing"))
SCRIPT = load_stream(recorded("cited_briefing"))
REQUEST = ModelRequest(model="another-providers-model", instructions="Use only the sources.",
                       question="What was decided about waste?", documents=DOCS, max_tokens=2000, effort="high")


# The contract every model client passes, against every recorded stream


class TestAProviderThatGivesCitations(ModelClientContract):
    @pytest.fixture
    def model(self):
        def make(script, structured):
            provider = Provider(script, structured, gives_citations=True)
            return client_for(provider), lambda: bool(provider.wires) and all(w.closed for w in provider.wires)

        return make


class TestAProviderThatGivesNoCitations(ModelClientContract):
    @pytest.fixture
    def model(self):
        def make(script, structured):
            provider = Provider(script, structured, gives_citations=False)
            return client_for(provider), lambda: bool(provider.wires) and all(w.closed for w in provider.wires)

        return make


# It is a skeleton, and is kept apart


def test_it_is_a_model_client_and_is_wired_into_nothing():
    client: ModelClient = client_for(Provider(SCRIPT, gives_citations=True))
    assert client.provider == "skeleton"
    assert "skeleton" not in " ".join(adapters.__all__) and not hasattr(adapters, "SkeletonProviderClient")
    # no settings can choose it: the one provider there is a real adapter for is still the only one
    from pathlib import Path

    from wts_core.settings import Settings, SettingsError, Site

    site = Site(name="A site", package="site", env_prefix="SITE", root=Path("."))
    settings = Settings(raw={"answer": {"provider": "skeleton"}}, data_dir=Path("."), config_path=Path("settings.toml"),
                        site=site)
    with pytest.raises(SettingsError, match='the only provider there is an adapter for is "anthropic"'):
        adapters.model_client(settings, site, {})
    import wts_core.adapters.skeleton_provider as skeleton

    assert "It is not a client for any real service, and no site" in " ".join((skeleton.__doc__ or "").split())


def test_the_request_is_the_providers_own_shape_and_carries_nothing_of_anthropics():
    provider = Provider(SCRIPT, gives_citations=True)
    list(client_for(provider).stream(REQUEST))
    [sent] = provider.requests
    assert sent["url"] == f"{BASE}/v1/respond" and sent["auth"] == "Bearer key-for-the-test"
    assert (sent["model"], sent["instructions"], sent["max_output_tokens"]) == ("another-providers-model",
                                                                                "Use only the sources.", 2000)
    assert sent["input"][:-1] == [document(d) for d in DOCS]  # in the order citations count them in
    assert sent["input"][-1] == {"type": "question", "text": "What was decided about waste?"}
    assert sent["stream"] is True and sent["cite"] is True
    assert not {"system", "messages", "search_result", "output_config", "betas"} & set(json.dumps(sent).split('"'))
    without = Provider(SCRIPT, gives_citations=False)
    list(client_for(without).stream(REQUEST))
    assert "cite" not in without.requests[0]


def test_what_it_cannot_do_it_does_not_claim():
    """``supports`` is what a pipeline may rely on. This provider has no prompt cache to ask for, no fallbacks and
    no effort setting, so none is claimed, and the request sends none."""
    assert client_for(Provider(SCRIPT, gives_citations=True)).supports == {"citations"}
    assert client_for(Provider(SCRIPT, gives_citations=False)).supports == frozenset()
    assert ScriptedModel(SCRIPT).supports > {"citations"}


def test_the_providers_own_token_counts_become_the_familys():
    """A provider with different usage fields is the adapter's to translate: its prompt tokens include those it
    read from its cache, and the family's cost formula prices each token once."""
    assert usage_of({"prompt_tokens": 9000, "cached_prompt_tokens": 7000, "completion_tokens": 600}) == Usage(
        input_uncached=2000, cache_read=7000, output=600)
    assert usage_of(None) == Usage() and usage_of({"prompt_tokens": 5, "cached_prompt_tokens": 9}) == Usage(
        cache_read=9)  # never a negative count, whatever is sent
    done = list(client_for(Provider(SCRIPT, gives_citations=True)).stream(REQUEST))[-1]
    recorded_usage = SCRIPT[-1].usage
    assert done.usage == Usage(input_uncached=recorded_usage.input_uncached, cache_read=recorded_usage.cache_read,
                               output=recorded_usage.output)
    assert done.stop_reason == "end_turn"  # the provider's "stop", in the word the sites' pipelines look for


def test_how_an_answer_ended_is_said_in_the_familys_words():
    for name, ours in (("refusal", "refusal"), ("max_tokens", "max_tokens")):
        script = load_stream(recorded(name))
        done = list(client_for(Provider(script, gives_citations=True)).stream(REQUEST))[-1]
        assert done.stop_reason == ours == script[-1].stop_reason


def test_a_refused_request_is_an_error_that_says_only_its_status():
    provider = Provider(SCRIPT, gives_citations=True, status=429)
    with pytest.raises(RuntimeError) as failed:
        list(client_for(provider).stream(REQUEST))
    assert str(failed.value) == "the provider answered 429" and "waste" not in str(failed.value)
    with pytest.raises(RuntimeError, match="the provider answered 429"):
        client_for(provider).structured(REQUEST, Reading)


def test_a_question_it_gives_nothing_for_carries_what_the_call_cost():
    with pytest.raises(NoStructuredAnswer) as nothing:
        client_for(Provider(SCRIPT, None, gives_citations=True)).structured(REQUEST, Reading)
    assert nothing.value.usage == Usage(input_uncached=400, output=30) and nothing.value.stop_reason == "refusal"


# Citations: passed on where given, never made up


def test_citations_a_provider_gives_are_passed_on_as_given_and_checked_like_any_other():
    """The same recorded briefing through the other provider's wire gives the same model events, and so the same
    checked report, as it does through the scripted client: the verifier reads events, never a provider."""
    theirs = list(client_for(Provider(SCRIPT, gives_citations=True)).stream(REQUEST))
    ours = list(ScriptedModel(SCRIPT).stream(REQUEST))
    assert theirs[:-1] == ours[:-1] and theirs[-1].blocks == ours[-1].blocks
    assert any(isinstance(e, CitationDelta) for e in theirs)
    report = checked(theirs[-1].blocks, DOCS, CHECKS.verifier, CHECKS.loaded_words)
    assert report == checked(ours[-1].blocks, DOCS, CHECKS.verifier, CHECKS.loaded_words)
    assert report["citations_total"] > 0 and report["citations_invalid"] == 0 and report["grounded_ratio"] == 1.0


def test_a_provider_that_gives_no_citations_is_given_none_by_the_adapter():
    """It does not invent them. The text arrives; nothing arrives as a citation; no block has one."""
    events = list(client_for(Provider(SCRIPT, gives_citations=False)).stream(REQUEST))
    assert not any(isinstance(e, CitationDelta) for e in events)
    done = events[-1]
    assert isinstance(done, Completed) and all(block.citations == () for block in done.blocks)
    assert "".join(b.text for b in done.blocks) == "".join(b.text for b in SCRIPT[-1].blocks)  # every word is there
    # even if such a provider should send something that looks like one, it is not passed on as a citation
    leaky = Provider(SCRIPT, gives_citations=True)  # the wire carries citations…
    client = SkeletonProviderClient(None, base_url=BASE, gives_citations=False,  # …to an adapter told there are none
                                    client=httpx.Client(transport=httpx.MockTransport(leaky)))
    events = list(client.stream(REQUEST))
    assert not any(isinstance(e, CitationDelta) for e in events) and all(b.citations == () for b in events[-1].blocks)


def test_without_citations_every_sentence_that_states_a_claim_is_flagged_and_nothing_passes_silently():
    """The contract a site must then meet. It runs the same checks on what it was given, and the verifier, with
    nothing to check a claim against, flags every one: the reader is shown a briefing with each point marked to
    check, never one that looks checked. (Or the site writes no briefings with that provider at all.)"""
    cited = checked(SCRIPT[-1].blocks, DOCS, CHECKS.verifier, CHECKS.loaded_words)
    done = list(client_for(Provider(SCRIPT, gives_citations=False)).stream(REQUEST))[-1]
    uncited = checked(done.blocks, DOCS, CHECKS.verifier, CHECKS.loaded_words)
    assert cited["grounded_ratio"] == 1.0 and cited["unsupported_segments"] == 0
    assert uncited["citations_total"] == 0 and uncited["grounded_ratio"] == 0.0
    assert uncited["unsupported_segments"] == len([s for s in uncited["segments"] if s["status"] == "unsupported"]) > 0
    assert not [s for s in uncited["segments"] if s["status"] == "cited"]  # not one sentence is shown as supported
    assert [s["text"] for s in uncited["segments"]] and "".join(s["text"] for s in uncited["segments"]).strip()


def test_had_the_adapter_made_citations_up_every_one_would_fail_the_verifier():
    """Why inventing them would not even work. A citation is a document and the words quoted from it, and the
    verifier looks for those words in that document. An adapter that "cited" each block to a document with words
    of its own would have every citation found invalid: the checks do not take an adapter's word for anything."""
    done = list(client_for(Provider(SCRIPT, gives_citations=False)).stream(REQUEST))[-1]
    made_up = tuple(Block(block.text, (Citation(document=n % len(DOCS), quoted=f"As the record shows: {block.text}"),))
                    for n, block in enumerate(done.blocks) if block.text.strip())
    report = checked(made_up, DOCS, CHECKS.verifier, CHECKS.loaded_words)
    assert report["citations_total"] == len(made_up) > 0
    assert report["citations_invalid"] == report["citations_total"]  # every cited block fails, none passes silently
    assert report["grounded_ratio"] == 0.0 and not [s for s in report["segments"] if s["status"] == "cited"]
