"""The event format of a streamed briefing (ADR 0003).

Two boundaries. **Model events** are what every model adapter emits: typed, with nothing of any one provider in
them. **Reader events** are what a site's pipeline sends to the reader's browser, and what the answer cache and
every saved briefing hold as JSON. That second form is a file format with months of saved data behind it, so it is
described here (``TypedDict``) and never rebuilt: unknown keys pass through untouched.

This module imports only ``wts_core.ports``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict

from wts_core.ports import Usage

__all__ = [
    "EVENTS_VERSION",
    "Answer",
    "Block",
    "Citation",
    "CitationDelta",
    "CitationEvent",
    "Completed",
    "ErrorEvent",
    "Event",
    "FinalEvent",
    "ModelEvent",
    "PlanEvent",
    "ReaderEvent",
    "SourcesEvent",
    "TextDelta",
    "TextEvent",
    "blocks_as_today",
    "to_reader",
]

# Today's shape is version 1. A saved or cached list of events with no version is version 1. A change adds a
# version and a reader for the old one: a saved briefing must always show what was originally shown.
EVENTS_VERSION = 1

# ---- from a model adapter --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class CitationDelta:
    """The model is citing a document: its place in the request (from 0, as the provider counts) and the words."""

    document: int | None
    quoted: str


@dataclass(frozen=True)
class Citation:
    document: int | None
    quoted: str


@dataclass(frozen=True)
class Block:
    """A run of the finished answer and the citations that support it (none: the model cited nothing for it)."""

    text: str
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True)
class Completed:
    """The whole message once the model has finished: what the checks read and what the cost is worked out from."""

    blocks: tuple[Block, ...]
    model: str
    stop_reason: str | None
    usage: Usage


type ModelEvent = TextDelta | CitationDelta | Completed

# ---- to a reader (today's JSON) --------------------------------------------------------------------------------


class Answer(TypedDict, total=False):
    """The verifier's report on a briefing, as every site sends and saves it."""

    segments: list[dict[str, Any]]
    markdown: str
    no_records: bool
    citations_total: int
    citations_invalid: int
    grounded_ratio: float
    unsupported_segments: int
    loaded_words: int
    quotes_total: int
    quotes_unverified: int
    rules: int  # the version of the checking rules that wrote it (absent on answers written before the package)


class PlanEvent(TypedDict):
    type: Literal["plan"]
    plan: dict[str, Any]  # the site's own: its filters and how it read the question
    usage: NotRequired[dict[str, int] | None]
    parse_error: NotRequired[str]


class SourcesEvent(TypedDict):
    """The records found, always sent before any text of the briefing."""

    type: Literal["sources"]
    sources: list[dict[str, Any]]  # the site's own cards
    candidates: NotRequired[int]
    semantic: NotRequired[bool]
    evidence: NotRequired[dict[str, Any]]


class TextEvent(TypedDict):
    type: Literal["text"]
    text: str


class CitationEvent(TypedDict):
    type: Literal["citation"]
    search_result_index: int | None
    cited_text: str


class FinalEvent(TypedDict):
    type: Literal["final"]
    answer: Answer | None
    usage: NotRequired[dict[str, int] | None]
    model: NotRequired[str | None]
    stop_reason: NotRequired[str | None]
    cached: NotRequired[bool]
    briefing_id: NotRequired[str]
    note: NotRequired[str]


class ErrorEvent(TypedDict):
    type: Literal["error"]
    message: str


# The shapes of the events every site sends: for reading, and for a function that makes one kind of event.
type ReaderEvent = PlanEvent | SourcesEvent | TextEvent | CitationEvent | FinalEvent | ErrorEvent

# One event of a briefing as it is passed about: what a site's pipeline makes, the briefing desk passes on, the
# answer cache and a saved briefing hold, and a reader receives. A plain dictionary, and honestly so: a site may
# send events of its own that ``ReaderEvent`` does not describe (Where MPs Stand's ``progress`` and
# ``interests``), and every key the package does not know passes through untouched. Everything that takes or
# gives events takes or gives this one type, so a site needs no cast between them.
type Event = dict[str, Any]


def to_reader(event: TextDelta | CitationDelta) -> Event:
    """A model event in the shape the sites send to a reader today (``TextEvent`` or ``CitationEvent``)."""
    if isinstance(event, TextDelta):
        return {"type": "text", "text": event.text}
    return {"type": "citation", "search_result_index": event.document, "cited_text": event.quoted}


def blocks_as_today(done: Completed) -> list[dict[str, Any]]:
    """The finished blocks as plain dictionaries: ``text`` and ``citations`` (each with ``cited_text`` and
    ``search_result_index``), which is what the verifier reads."""
    return [{"text": b.text,
             "citations": [{"type": "search_result_location", "cited_text": c.quoted,
                            "search_result_index": c.document, "source": None} for c in b.citations]}
            for b in done.blocks]
