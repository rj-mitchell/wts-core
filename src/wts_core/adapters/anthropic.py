"""The model behind ``ports.ModelClient``, at Anthropic: briefings streamed with search-result citations, and
questions read into a schema.

This is the three sites' ``rag/answer.py`` (``make_client``, ``api_key``, ``cached_system``, ``usage_dict``,
``_block_to_dict``, the streaming loop and the retry without the fallback beta) and the ``messages.parse`` call of
each ``rag/query_parse.py``, which were the same but for the environment prefix. Every call to the SDK keeps the
shape the sites send today. What a site keeps is everything that is its own: its instructions, the text of its
question to the model, how a source becomes a document, its models, efforts and ``max_tokens``.

Two things are new. That the API refused the fallback beta is remembered on the client, so a site that keeps one
client for the life of its process finds out once (each site made a new ``Answerer`` for every briefing, and so
made a refused request first every time). And how the instructions are cached is the request's to say: "short" is
what the sites send today, "long" asks for the one-hour lifetime the SDK documents (``ttl``), "off" sends them as
plain text.

``anthropic`` is imported only inside functions, so importing this module needs nothing installed.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator, Iterator, Mapping
from typing import Any

from wts_core.events import Block, Citation, CitationDelta, Completed, ModelEvent, TextDelta
from wts_core.ports import Document, ModelRequest, Schema, Usage
from wts_core.settings import Settings, Site

__all__ = [
    "BASE_URL",
    "FALLBACK_BETA",
    "KEY_FILE",
    "AnthropicClient",
    "api_key",
    "base_url",
    "from_settings",
    "has_credentials",
    "search_result",
]

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
KEY_FILE = "anthropic_api_key"  # in the data folder; written by hand, or by a site's own command
BASE_URL = "https://api.anthropic.com"


def api_key(site: Site, settings: Settings, env: Mapping[str, str] | None = None) -> str | None:
    """``<PREFIX>_ANTHROPIC_API_KEY``, then ``ANTHROPIC_API_KEY``, then the key file in the data folder.

    The site's own name avoids clashing with tools that reserve the ANTHROPIC_* variables for themselves (such as
    a Claude Code cloud session, which withholds them). The key file is for running on your own computer, where
    setting environment variables is a chore.
    """
    source = os.environ if env is None else env
    key = site.env("ANTHROPIC_API_KEY", source) or source.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        return (settings.data_dir / KEY_FILE).read_text().strip() or None
    except OSError:
        return None


def base_url(site: Site, env: Mapping[str, str] | None = None) -> str:
    """``<PREFIX>_ANTHROPIC_BASE_URL``, else the API itself.

    Never an ``ANTHROPIC_BASE_URL`` inherited from another tool: the site talks to the API itself. (The address is
    always passed to the SDK, which would otherwise read that variable.)
    """
    return site.env("ANTHROPIC_BASE_URL", env) or BASE_URL


def has_credentials(site: Site, settings: Settings, env: Mapping[str, str] | None = None) -> bool:
    """Whether there is anything to call the model with: a key from ``api_key``, or the SDK's own
    ``ANTHROPIC_AUTH_TOKEN``. Without either a site shows the evidence only, as each does today."""
    source = os.environ if env is None else env
    return bool(api_key(site, settings, source) or source.get("ANTHROPIC_AUTH_TOKEN"))


def from_settings(settings: Settings, site: Site, env: Mapping[str, str] | None = None) -> AnthropicClient:
    """The client a site uses: its key and address from the environment, and the timings every site shares."""
    return AnthropicClient(api_key(site, settings, env), base_url=base_url(site, env))


def search_result(document: Document) -> dict[str, Any]:
    """One source as the ``search_result`` block each site's ``Source.search_result()`` builds: the same keys in
    the same order, one text block for each passage, citations on."""
    return {
        "type": "search_result",
        "source": document.source,
        "title": document.title,
        "content": [{"type": "text", "text": p} for p in document.passages],
        "citations": {"enabled": True},
    }


def _instructions(request: ModelRequest) -> str | list[dict[str, Any]]:
    """The instructions as the ``system`` of a request.

    "short": one cacheable block. They are the same for every request (apart from the date), so repeat requests
    within five minutes read them from Anthropic's cache at a fraction of the price. The documents and the question
    come after them and are not cached. "long" asks for the one-hour lifetime instead, which costs more to write.
    "off": plain text, as the sites' evaluation judges send theirs.
    """
    if request.cache_instructions == "off":
        return request.instructions
    cache: dict[str, Any] = {"type": "ephemeral"}
    if request.cache_instructions == "long":
        cache["ttl"] = "1h"
    elif request.cache_instructions != "short":
        raise ValueError(f"cache_instructions must be off, short or long, not {request.cache_instructions!r}")
    return [{"type": "text", "text": request.instructions, "cache_control": cache}]


def _usage_dict(usage: Any) -> dict[str, int]:
    """Token counts in the sites' own form (their ``usage_dict``): input_tokens includes cache writes, and
    cache_write_tokens says how many, for pricing."""
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
    writes = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    counts = {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0) + writes,
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "cache_read_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        "cache_write_tokens": writes,
    }
    # the one-hour cache costs more to write, so its share is kept apart for pricing (none on the sites today)
    long = getattr(getattr(usage, "cache_creation", None), "ephemeral_1h_input_tokens", 0)
    if isinstance(long, int) and long > 0:
        counts["cache_write_long_tokens"] = long
    return counts


def _usage(usage: Any) -> Usage:
    """The SDK's usage as a ``Usage``, by the road the sites take today (``usage_dict``, then ``token_counts``), so
    ``as_stored()`` gives exactly what each site records."""
    return Usage.from_mapping(_usage_dict(usage))


def _block(block: Any) -> Block | None:
    """A text block of the finished message with its citations; anything else (thinking, say) is dropped."""
    if getattr(block, "type", None) != "text":
        return None
    cites = tuple(Citation(document=getattr(c, "search_result_index", None), quoted=getattr(c, "cited_text", ""))
                  for c in getattr(block, "citations", None) or [])
    return Block(text=block.text, citations=cites)


class AnthropicClient:
    """``ports.ModelClient`` over the Anthropic SDK.

    A briefing streams for a minute or two at most: five minutes without a byte means the connection is dead, and
    ten seconds is ample to connect. Two retries for a refused or dropped request (the SDK waits between them). The
    same for every site of Where They Stand.

    Keep one client for the life of the process: it remembers that the API refused the fallback beta
    (``fallbacks_refused``), and then stops asking.
    """

    provider = "anthropic"
    supports = frozenset({"caching", "long_cache", "fallbacks", "effort", "citations"})

    def __init__(self, api_key: str | None, *, base_url: str, timeout: float = 300.0, connect: float = 10.0,
                 max_retries: int = 2, client: Any = None) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.timeout, self.connect, self.max_retries = timeout, connect, max_retries
        self.fallbacks_refused = False
        self._client = client  # an SDK client made elsewhere: tests pass a fake

    @property
    def client(self) -> Any:
        """The SDK's client, made when first needed."""
        if self._client is None:
            import anthropic

            # anthropic.Timeout, not httpx.Timeout: the SDK has its own copy of httpx and refuses the other's.
            options: dict[str, Any] = {"base_url": self.base_url, "max_retries": self.max_retries,
                                       "timeout": anthropic.Timeout(self.timeout, connect=self.connect)}
            # with no key of the site's, the SDK's own credentials apply
            self._client = (anthropic.Anthropic(api_key=self.api_key, **options) if self.api_key
                            else anthropic.Anthropic(**options))
        return self._client

    # ---- a briefing ---------------------------------------------------------------------------------------------

    def stream(self, request: ModelRequest) -> Generator[ModelEvent, None, None]:
        """Text and citations as they are written, then one ``Completed`` (``ports.ModelStream``). Closing it
        closes the SDK's stream, so a briefing nobody is reading stops being written."""
        content: list[dict[str, Any]] = [search_result(d) for d in request.documents]
        content.append({"type": "text", "text": request.question})
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": int(request.max_tokens),
            "system": _instructions(request),
            "messages": [{"role": "user", "content": content}],
        }
        if request.effort:
            kwargs["output_config"] = {"effort": request.effort}
        fallbacks = request.fallbacks and not self.fallbacks_refused
        try:
            yield from self._run(kwargs, fallbacks=fallbacks)
        except Exception as exc:  # the fallback beta may be unavailable on some accounts/platforms
            import anthropic

            if fallbacks and isinstance(exc, anthropic.BadRequestError) and "fallback" in str(exc).lower():
                log.warning("server-side fallbacks rejected; retrying without them, and not asking again")
                self.fallbacks_refused = True
                yield from self._run(kwargs, fallbacks=False)
            else:
                raise

    def _run(self, kwargs: dict[str, Any], fallbacks: bool) -> Iterator[ModelEvent]:
        if fallbacks:
            ctx = self.client.beta.messages.stream(**kwargs, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            ctx = self.client.messages.stream(**kwargs)
        with ctx as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue
                d = event.delta
                if d.type == "text_delta":
                    yield TextDelta(d.text)
                elif d.type == "citations_delta":
                    c = d.citation
                    yield CitationDelta(document=getattr(c, "search_result_index", None),
                                        quoted=getattr(c, "cited_text", ""))
            msg = stream.get_final_message()
        blocks = tuple(b for b in (_block(x) for x in msg.content) if b)
        yield Completed(blocks=blocks, model=msg.model, stop_reason=msg.stop_reason, usage=_usage(msg.usage))

    # ---- a question read into a schema --------------------------------------------------------------------------

    def structured[T: Schema](self, request: ModelRequest, schema: type[T]) -> tuple[T, Usage]:
        """One answer that fits ``schema``, and what it cost: the sites' ``messages.parse`` call. The question is
        sent as the whole of the user's message. The fallback beta is not used here, as it is not today. A refusal,
        or an answer with nothing in it, raises ``RuntimeError`` with the words the sites' logs have today."""
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": int(request.max_tokens),
            "system": _instructions(request),
            "messages": [{"role": "user", "content": request.question}],
        }
        if request.effort:
            kwargs["output_config"] = {"effort": request.effort}
        resp = self.client.messages.parse(**kwargs, output_format=schema)
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            raise RuntimeError(f"query parser returned no output (stop_reason={resp.stop_reason})")
        parsed: T = resp.parsed_output
        return parsed, _usage(resp.usage)
