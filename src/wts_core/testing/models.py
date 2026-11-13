"""A model that says what it is told, and the file format of a recorded stream.

``ScriptedModel`` is a ``ports.ModelClient`` for tests: it replays a list of model events (or a recorded file) and
keeps every request it was given, so a test can read exactly what would have been sent to the model.

A recorded stream is a text file of JSON lines. The first line may be a header (``{"recording": 1, …}``: how many
documents the request had, the documents themselves under ``sources`` if they were kept, and anything worth knowing
about where it came from); each line after it is one model event in the order the adapter emitted it::

    {"event": "text", "text": "Ministers said "}
    {"event": "citation", "document": 0, "quoted": "the scheme will open in April"}
    {"event": "completed", "blocks": [{"text": "…", "citations": [{"document": 0, "quoted": "…"}]}],
     "model": "…", "stop_reason": "end_turn",
     "usage": {"input_uncached": 0, "cache_write": 0, "cache_read": 0, "output": 0}}

Nothing of any one provider is in the file: it is what crosses the boundary every adapter shares (ADR 0003), so a
recording made through one adapter can be replayed to test anything downstream of any other.
"""

from __future__ import annotations

import json
from collections.abc import Generator, Iterable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from wts_core.events import Block, Citation, CitationDelta, Completed, ModelEvent, TextDelta
from wts_core.ports import Document, ModelRequest, Schema, Usage

__all__ = ["RECORDING_VERSION", "ScriptedModel", "load_documents", "load_header", "load_stream", "record_stream",
           "recorded"]

RECORDING_VERSION = 1
_RECORDED = Path(__file__).parent / "recorded"


def recorded(name: str) -> Path:
    """One of the recorded streams that ship with the package, by its name without the ending
    (``recorded("cited_briefing")``)."""
    path = _RECORDED / f"{name}.jsonl"
    if not path.exists():
        have = ", ".join(sorted(p.stem for p in _RECORDED.glob("*.jsonl")))
        raise FileNotFoundError(f"no recorded stream called {name!r}: there are {have}")
    return path


def _line(event: ModelEvent) -> dict[str, Any]:
    if isinstance(event, TextDelta):
        return {"event": "text", "text": event.text}
    if isinstance(event, CitationDelta):
        return {"event": "citation", "document": event.document, "quoted": event.quoted}
    return {"event": "completed",
            "blocks": [{"text": b.text, "citations": [{"document": c.document, "quoted": c.quoted}
                                                      for c in b.citations]} for b in event.blocks],
            "model": event.model, "stop_reason": event.stop_reason, "usage": {k: v for k, v in asdict(event.usage).items() if v or k != "cache_write_long"}}


def _event(raw: dict[str, Any]) -> ModelEvent:
    kind = raw.get("event")
    if kind == "text":
        return TextDelta(raw["text"])
    if kind == "citation":
        return CitationDelta(document=raw["document"], quoted=raw["quoted"])
    if kind == "completed":
        blocks = tuple(Block(b["text"], tuple(Citation(c["document"], c["quoted"]) for c in b.get("citations", [])))
                       for b in raw["blocks"])
        return Completed(blocks=blocks, model=raw["model"], stop_reason=raw["stop_reason"],
                         usage=Usage(**raw.get("usage", {})))
    raise ValueError(f"not a model event: {raw!r}")


def record_stream(path: Path, events: Iterable[ModelEvent], *, documents: Sequence[Document] | int = 0,
                  **about: Any) -> Path:
    """Write a stream of model events as a recording. ``documents`` are the documents the request had (what a
    citation's number counts into), or just how many; ``about`` is anything else for the header (never a reader's
    question)."""
    header: dict[str, Any] = {"recording": RECORDING_VERSION}
    if isinstance(documents, int):
        header["documents"] = documents
    else:
        header["documents"] = len(documents)
        header["sources"] = [{"title": d.title, "source": d.source, "passages": list(d.passages)} for d in documents]
    lines = [{**header, **about}, *(_line(e) for e in events)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8")
    return path


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def load_header(path: Path) -> dict[str, Any]:
    """A recording's header; empty when it has none."""
    lines = _lines(path)
    return lines[0] if lines and "recording" in lines[0] else {}


def load_documents(path: Path) -> tuple[Document, ...]:
    """The documents of a recording's request, numbered from 1: those kept in its header, or stand-ins when it
    says only how many there were."""
    header = load_header(path)
    if "sources" in header:
        return tuple(Document(n, s["title"], s["source"], tuple(s["passages"]))
                     for n, s in enumerate(header["sources"], start=1))
    return tuple(Document(n, f"Source {n}", f"https://example.org/{n}", (f"Passage of source {n}.",))
                 for n in range(1, int(header.get("documents", 0)) + 1))


def load_stream(path: Path) -> list[ModelEvent]:
    """The model events of a recording, in order."""
    return [_event(raw) for raw in _lines(path) if "recording" not in raw]


class ScriptedModel:
    """A ``ports.ModelClient`` that replays ``script`` (model events, or the path of a recording) each time it is
    asked for a briefing, and records every request.

    ``requests`` holds each ``ModelRequest`` given to ``stream``; ``structured_requests`` each request and schema
    given to ``structured``, which returns ``structured`` (validated by the schema when it is a plain mapping) and
    ``structured_usage``. ``closed`` counts the streams that were closed before they finished: a reader who left.
    ``error``, if given, is raised when the script has been replayed, in place of a stream that ends well: the
    script then needs no ``Completed``.
    """

    provider = "scripted"
    supports = frozenset({"caching", "long_cache", "fallbacks", "effort", "citations"})

    def __init__(self, script: Sequence[ModelEvent] | Path, *, structured: Any = None,
                 structured_usage: Usage | None = None, error: Exception | None = None) -> None:
        self.script: list[ModelEvent] = load_stream(script) if isinstance(script, Path) else list(script)
        done = [i for i, e in enumerate(self.script) if isinstance(e, Completed)]
        if error is None and done != [len(self.script) - 1]:
            raise ValueError("a script is text and citations, then exactly one Completed, last")
        if error is not None and done:
            raise ValueError("a script that ends in an error has no Completed")
        self.structured_answer = structured
        self.structured_usage = structured_usage or Usage()
        self.error = error
        self.requests: list[ModelRequest] = []
        self.structured_requests: list[tuple[ModelRequest, type[Any]]] = []
        self.started = 0
        self.closed = 0

    def stream(self, request: ModelRequest) -> Generator[ModelEvent, None, None]:
        self.requests.append(request)
        return self._replay()

    def _replay(self) -> Generator[ModelEvent, None, None]:
        self.started += 1
        try:
            yield from self.script
        except GeneratorExit:
            self.closed += 1
            raise
        if self.error is not None:
            raise self.error

    def structured[T: Schema](self, request: ModelRequest, schema: type[T]) -> tuple[T, Usage]:
        self.structured_requests.append((request, schema))
        if self.structured_answer is None:
            raise RuntimeError("query parser returned no output (stop_reason=refusal)")
        answer = self.structured_answer
        return (answer if isinstance(answer, schema) else schema.model_validate(answer)), self.structured_usage
