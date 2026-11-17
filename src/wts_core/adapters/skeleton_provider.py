"""A template for an adapter to a second model provider. It is not a client for any real service, and no site
uses it.

Start here, with ``docs/EXTENDING.md`` ("A second provider"), when adding a real provider: replace the invented
wire shape below with the provider's own and keep the translation into the family's events. The template meets
``ports.ModelClient`` over a made-up HTTP interface with ``httpx`` (which the ``offsite`` extra already brings) and
passes ``testing.ModelClientContract`` against the recorded streams that ship with the package, which shows the
interface can be met without the Anthropic SDK (ADR 0002). It is not exported from ``wts_core.adapters``, and
``adapters.model_client`` does not know it.

The invented wire shape:

* a briefing: ``POST {base_url}/v1/respond`` with ``{"model", "instructions", "input": [documents…, question],
  "max_output_tokens", "stream": true}`` and, if the provider can cite, ``"cite": true``. It answers with lines of
  ``data: {…}``: ``{"type": "text", "text": …}`` as the words are written; ``{"type": "citation", "document": n,
  "quote": …}`` before the words a citation supports (``document`` counted from 0, in the order the documents were
  sent); and last ``{"type": "done", "model", "finish", "output": [{"text", "citations": [{"document",
  "quote"}]}], "usage": {"prompt_tokens", "cached_prompt_tokens", "completion_tokens"}}``;
* a question read into a schema: the same address with ``"response_schema"`` and no ``"stream"``; it answers
  ``{"output_text": "…" or null, "finish", "usage"}``: the JSON as the model wrote it, which may be cut off or
  not JSON at all.

Citations are the hard part (ADR 0002). The checks need the document a citation points to and the words quoted
from it. Where a provider gives both, the adapter passes them on as given. Where it gives none
(``gives_citations=False``), the adapter emits the text with no citation and leaves ``"citations"`` out of
``supports``. A site must then either run the checks as they are, so every claim is flagged as unsupported
(``tests/test_swap_provider.py`` shows this), or write no briefings with that provider and show the sources only.
An adapter must never invent citations.

``httpx`` is imported only inside functions, so importing this module needs nothing installed.
"""

from __future__ import annotations

import json
from collections.abc import Generator, Mapping
from typing import Any

from wts_core.events import Block, Citation, CitationDelta, Completed, ModelEvent, TextDelta
from wts_core.ports import Document, ModelRequest, Schema, Usage, read_structured

__all__ = ["FINISH", "SkeletonProviderClient", "document", "usage_of"]

# the provider's words for how an answer ended, in the family's (which are Anthropic's: the sites' pipelines look
# for "refusal", and the record of each briefing keeps the word)
FINISH: Mapping[str, str] = {"stop": "end_turn", "length": "max_tokens", "refused": "refusal"}


def document(doc: Document) -> dict[str, Any]:
    """One source as this provider is sent it. The order they are sent in is the order citations count them in."""
    return {"type": "document", "title": doc.title, "source": doc.source, "passages": list(doc.passages)}


def usage_of(raw: Mapping[str, Any] | None) -> Usage:
    """This provider's token counts as a ``Usage``. Its ``prompt_tokens`` include those read from its cache, and it
    has no charge for writing to one: a provider with other usage fields is the adapter's to translate, so that
    the cost formula and the spending record never learn of it."""
    counts = raw or {}
    cached = max(0, int(counts.get("cached_prompt_tokens") or 0))
    prompt = max(cached, int(counts.get("prompt_tokens") or 0))
    return Usage(input_uncached=prompt - cached, cache_read=cached,
                 output=max(0, int(counts.get("completion_tokens") or 0)))


class SkeletonProviderClient:
    """``ports.ModelClient`` over the invented wire shape above. Not for use: see the module's docstring.

    ``gives_citations`` says whether the provider returns the document and the quoted words for what it writes.
    With False nothing is asked for and nothing is emitted as a citation, whatever the provider sends, and
    ``supports`` says so. ``client`` is an ``httpx.Client`` made elsewhere (tests pass one with a transport that
    answers from recorded streams); without it one is made when first needed."""

    provider = "skeleton"

    def __init__(self, api_key: str | None, *, base_url: str, gives_citations: bool, timeout: float = 300.0,
                 connect: float = 10.0, client: Any = None) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.gives_citations = gives_citations
        self.timeout, self.connect = timeout, connect
        # what a pipeline may rely on: no prompt caching to ask for, no fallbacks, no effort setting; and
        # citations only where the provider really gives them
        self.supports: frozenset[str] = frozenset({"citations"}) if gives_citations else frozenset()
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import httpx

            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            self._client = httpx.Client(headers=headers, timeout=httpx.Timeout(self.timeout, connect=self.connect))
        return self._client

    def _body(self, request: ModelRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model, "instructions": request.instructions,
            "input": [*(document(d) for d in request.documents), {"type": "question", "text": request.question}],
            "max_output_tokens": int(request.max_tokens),
        }
        if self.gives_citations:
            body["cite"] = True
        # ``effort``, ``cache_instructions`` and ``fallbacks`` have nothing to become here: ``supports`` names none
        # of them, so a pipeline that reads it knows they were not applied
        return body

    # A briefing

    def stream(self, request: ModelRequest) -> Generator[ModelEvent, None, None]:
        """Text (and citations, where the provider gives them) as they are written, then one ``Completed``.
        Closing the stream closes the connection, which stops the model."""
        done: Completed | None = None
        with self.client.stream("POST", f"{self.base_url}/v1/respond", json={**self._body(request), "stream": True}) \
                as response:
            if response.status_code >= 400:
                # the status alone: an error's body can repeat the question it was sent
                raise RuntimeError(f"the provider answered {response.status_code}")
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[len("data:"):])
                kind = event.get("type")
                if kind == "text":
                    yield TextDelta(str(event.get("text", "")))
                elif kind == "citation" and self.gives_citations:
                    yield CitationDelta(document=event.get("document"), quoted=str(event.get("quote", "")))
                elif kind == "done":
                    done = self._completed(event, request)
                    break
        if done is None:
            raise RuntimeError("the provider's stream ended without saying it was done")
        yield done

    def _completed(self, event: Mapping[str, Any], request: ModelRequest) -> Completed:
        blocks = tuple(
            Block(text=str(part.get("text", "")),
                  # passed on as given, never made: with a provider that gives none, a block has none
                  citations=tuple(Citation(document=c.get("document"), quoted=str(c.get("quote", "")))
                                  for c in (part.get("citations") or [])) if self.gives_citations else ())
            for part in (event.get("output") or []))
        finish = str(event.get("finish") or "")
        return Completed(blocks=blocks, model=str(event.get("model") or request.model),
                         stop_reason=FINISH.get(finish, finish or None), usage=usage_of(event.get("usage")))

    # A question read into a schema

    def structured[T: Schema](self, request: ModelRequest, schema: type[T]) -> tuple[T, Usage]:
        """One answer that fits ``schema``, and what it cost. The provider's answer is taken first, with its
        usage, and read here: a refusal, an answer with nothing in it, one cut off, one that is not JSON and one
        that does not fit all raise ``ports.NoStructuredAnswer`` carrying the token counts of the call (it was
        paid for). An adapter that lets its provider's library read the answer must make sure of the same."""
        response = self.client.post(f"{self.base_url}/v1/respond",
                                    json={**self._body(request), "response_schema": schema.model_json_schema()})
        if response.status_code >= 400:
            raise RuntimeError(f"the provider answered {response.status_code}")
        answer = response.json()
        usage, finish = usage_of(answer.get("usage")), str(answer.get("finish") or "")
        stop_reason = FINISH.get(finish, finish or None)
        text = answer.get("output_text")
        return read_structured(schema, text if isinstance(text, str) else None, usage=usage,
                               stop_reason=stop_reason), usage
