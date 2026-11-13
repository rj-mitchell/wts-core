"""Every interface something may be swapped behind, and the small values they pass (ADR 0002).

Shared logic depends on these, never on an outside library: only the modules under ``wts_core.adapters`` import
one. A new model is a settings change; a new provider, embedding model, vector store or off-site store is one
adapter that passes its contract suite in ``wts_core.testing``.

This module imports nothing from the rest of the package.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self, runtime_checkable

if TYPE_CHECKING:
    from wts_core.events import ModelEvent

__all__ = [
    "SYSTEM_CLOCK",
    "SYSTEM_RANDOM",
    "AnswerCache",
    "BriefingConfig",
    "BriefingLog",
    "BriefingRecord",
    "Busy",
    "Clock",
    "Document",
    "Embedder",
    "InProgress",
    "IndexMeta",
    "IndexOutOfDate",
    "KeyValue",
    "Limiter",
    "ModelClient",
    "ModelRequest",
    "OffsiteError",
    "OffsiteStore",
    "OffsiteUnavailable",
    "Outcome",
    "Price",
    "Pricing",
    "Random",
    "Schema",
    "SpendingRecord",
    "StoredFile",
    "SystemClock",
    "SystemRandom",
    "UnknownModel",
    "Usage",
    "VectorIndex",
    "Vector",
    "Vectors",
]

# ---- time and chance -------------------------------------------------------------------------------------------


class Clock(Protocol):
    """Where the time comes from, so tests can fix it."""

    def now(self) -> datetime:
        """The time now, timezone-aware, in UTC."""
        ...

    def monotonic(self) -> float:
        """Seconds from a clock that never goes backwards, for measuring how long things take."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class Random(Protocol):
    """Where chance comes from: briefing ids, the day's salt, an experiment's arm."""

    def token(self, nbytes: int) -> str:
        """A URL-safe random string from ``nbytes`` random bytes."""
        ...

    def token_hex(self, nbytes: int) -> str: ...

    def choice[T](self, items: Sequence[T], weights: Sequence[float]) -> T: ...


class SystemRandom:
    _random = secrets.SystemRandom()

    def token(self, nbytes: int) -> str:
        return secrets.token_urlsafe(nbytes)

    def token_hex(self, nbytes: int) -> str:
        return secrets.token_hex(nbytes)

    def choice[T](self, items: Sequence[T], weights: Sequence[float]) -> T:
        return self._random.choices(list(items), weights=list(weights), k=1)[0]


SYSTEM_CLOCK: Clock = SystemClock()
SYSTEM_RANDOM: Random = SystemRandom()

# ---- the model -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    """One model call's token counts, with unambiguous names.

    The sites' stored and cached data use two older forms, in which "input tokens" means two different things:
    the SDK's own names (``input_tokens`` leaves cache writes out) and the sites' own (``input_tokens`` includes
    them, with ``cache_write_tokens`` saying how many). ``from_mapping`` reads either; ``as_stored`` writes the
    sites' own, so stored data keeps its meaning.
    """

    input_uncached: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0
    # of ``cache_write``, how many went to the one-hour cache, which costs more to write (0 on every site today)
    cache_write_long: int = 0

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> Usage:
        u = raw or {}
        # the site's own name for cache reads is used whenever it is present, even at 0, before the SDK's
        reads = u.get("cache_read_tokens")
        if reads is None:
            reads = u.get("cache_read_input_tokens")
        if "cache_write_tokens" in u:
            writes = int(u.get("cache_write_tokens") or 0)
            uncached = int(u.get("input_tokens") or 0) - writes
        else:
            writes = int(u.get("cache_creation_input_tokens") or 0)
            uncached = int(u.get("input_tokens") or 0)
        return cls(input_uncached=uncached, cache_write=writes, cache_read=int(reads or 0),
                   output=int(u.get("output_tokens") or 0),
                   cache_write_long=max(0, min(writes, int(u.get("cache_write_long_tokens") or 0))))

    def as_stored(self) -> dict[str, int]:
        """The sites' own form: ``input_tokens`` includes the cache writes. ``cache_write_long_tokens`` is there
        only when there were any, so what the sites store today is unchanged."""
        stored = {"input_tokens": self.input_uncached + self.cache_write, "output_tokens": self.output,
                  "cache_read_tokens": self.cache_read, "cache_write_tokens": self.cache_write}
        if self.cache_write_long:
            stored["cache_write_long_tokens"] = self.cache_write_long
        return stored

    def __add__(self, other: Usage) -> Usage:
        return Usage(self.input_uncached + other.input_uncached, self.cache_write + other.cache_write,
                     self.cache_read + other.cache_read, self.output + other.output,
                     self.cache_write_long + other.cache_write_long)


@dataclass(frozen=True)
class Document:
    """One source given to the model: its number in the request (from 1), and its text in passages."""

    number: int
    title: str
    source: str
    passages: tuple[str, ...]


@dataclass(frozen=True)
class ModelRequest:
    model: str
    instructions: str
    question: str
    documents: tuple[Document, ...] = ()
    max_tokens: int = 16000
    effort: str | None = None
    # "short" is the provider's ordinary prompt cache (five minutes at Anthropic); "long" an extended one where
    # the provider offers it; "off" sends the instructions uncached
    cache_instructions: Literal["off", "short", "long"] = "short"
    fallbacks: bool = True


class Schema(Protocol):
    """What ``ModelClient.structured`` needs of a schema class: Pydantic's two methods, so this module needn't
    import Pydantic."""

    @classmethod
    def model_json_schema(cls) -> dict[str, Any]: ...

    @classmethod
    def model_validate(cls, obj: Any) -> Self: ...


class ModelClient(Protocol):
    """A model that writes briefings from documents, with citations, and reads questions into a schema."""

    provider: str
    supports: frozenset[str]  # of "caching", "long_cache", "fallbacks", "effort", "citations"

    def stream(self, request: ModelRequest) -> Iterator[ModelEvent]:
        """Text and citations as they are written, then exactly one ``Completed``. Closing the iterator stops the
        model."""
        ...

    def structured[T: Schema](self, request: ModelRequest, schema: type[T]) -> tuple[T, Usage]:
        """One answer that fits ``schema`` (reading a question into filters, say), and what it cost."""
        ...


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens; cache writes cost the input price times ``cache_write_multiplier``, and
    writes to the one-hour cache the input price times ``cache_write_long_multiplier`` (twice the input price is
    Anthropic's published rate; no site uses that cache today)."""

    input: float
    output: float
    cache_read: float
    cache_write_multiplier: float = 1.25
    cache_write_long_multiplier: float = 2.0


class UnknownModel(LookupError):
    """A model named in settings has no price of its own. Raised only by a site that asks for strict pricing at
    start-up (``usage.PriceTable.require(models, base_counts=False)``); otherwise, as on every site today, a model
    with no entry is costed at the site's base prices."""


class Pricing(Protocol):
    def price_for(self, model: str | None) -> Price: ...

    def cost(self, usage: Usage | None, model: str | None) -> float:
        """Cost in US dollars, rounded to six places."""
        ...


# ---- search by meaning -----------------------------------------------------------------------------------------

# a row of floats, and rows of them: numpy arrays in today's adapters, which this module does not import
type Vector = Any
type Vectors = Any


@runtime_checkable
class Embedder(Protocol):
    id: str  # the model's name and, where known, a hash of its weights: what an index was built with
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> Vectors: ...

    def embed_query(self, text: str) -> Vector: ...


@dataclass(frozen=True)
class IndexMeta:
    """What an index was built with, stored beside it and checked by every reader and writer."""

    embedder_id: str
    dimension: int
    number_type: str = "float32"
    schema_version: int = 1


class IndexOutOfDate(RuntimeError):
    """The index was built with another embedder or schema: rebuild it. Vectors from two models are never mixed."""

    def __init__(self, stored: IndexMeta, wanted: IndexMeta):
        super().__init__(f"the search index was built with {stored}, and {wanted} is wanted: rebuild it")
        self.stored, self.wanted = stored, wanted


class VectorIndex(Protocol):
    meta: IndexMeta

    def replace(self, keys: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None: ...

    def add_vectors(self, keys: Sequence[str], rows: Sequence[Mapping[str, Any]], vectors: Vectors) -> None: ...

    def search_words(self, query: str, where: str | None, limit: int) -> list[dict[str, Any]]: ...

    def search_meaning(self, vector: Vector, where: str | None, limit: int) -> list[dict[str, Any]]: ...

    def build_indexes(self) -> None: ...

    def tidy(self) -> None: ...


# ---- off-site copies -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredFile:
    name: str
    id: str = ""
    size: int = 0


class OffsiteError(RuntimeError):
    """An off-site copy could not be stored, listed or deleted. What every ``OffsiteStore`` raises, with the reason
    in words for the owner (never the key)."""


class OffsiteUnavailable(OffsiteError):
    """The store could not be reached, or did not answer as it should: not a refusal of one request. A store that
    refuses to delete an old copy leaves the new one stored all the same; one that cannot be reached does not."""


class OffsiteStore(Protocol):
    """Somewhere away from the server that keeps copies of backups. It raises ``OffsiteError``."""

    name: str  # the bucket, for messages

    def put(self, path: Path) -> StoredFile: ...

    def list(self, prefix: str) -> list[StoredFile]:
        """This site's files, oldest first by name."""
        ...

    def delete(self, file: StoredFile) -> None: ...

    def close(self) -> None:
        """Give up any connection held. Called after each use; the next use may start another."""
        ...


# ---- limits ----------------------------------------------------------------------------------------------------


class Limiter(Protocol):
    def allow(self, key: str) -> bool: ...


@dataclass(frozen=True)
class Busy:
    """Why a briefing can't start now: this visitor has too many in progress, or the site has."""

    reason: Literal["visitor", "site"]


class InProgress(Protocol):
    def start(self, key: str) -> Busy | None: ...

    def finish(self, key: str) -> None: ...

    def pending_usd(self, besides: int = 0) -> float: ...


# ---- storage, one small interface per need ---------------------------------------------------------------------


class KeyValue(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...

    def set_if_absent(self, key: str, value: str) -> None: ...

    def delete(self, key: str) -> None: ...

    def delete_like(self, pattern: str, *, keep: str | None = None) -> None:
        """Delete keys matching an SQL LIKE pattern, except ``keep``."""
        ...


class SpendingRecord(Protocol):
    def add(self, kind: str, model: str | None, usage: Usage | Mapping[str, Any] | None, *,
            visitor: str | None = None, account: int | None = None) -> float:
        """Record one model call and return its cost. ``usage`` may be a ``Usage`` or the token counts in either of
        the forms the sites store today. Nothing is written when there is no usage."""
        ...

    def spent_since(self, since: str) -> float: ...

    def briefings_today(self, *, visitor: str | None = None, account: int | None = None) -> int: ...


# ---- the record of each briefing (ADR 0012) ---------------------------------------------------------------------

type Outcome = Literal["completed", "cached", "no_records", "sources_only", "paused_cap", "paused_limit", "busy",
                       "left", "error"]


@dataclass
class BriefingRecord:
    """How one briefing went: written once, by the briefing desk, however it ended. Nothing in it identifies the
    reader: no visitor code, no address, nothing from the request's headers. Times are milliseconds from the
    question's arrival; a stage that was not reached is None."""

    id: str
    at: str  # ISO 8601, UTC, to the second
    outcome: Outcome
    kind: Literal["reader", "check", "eval"] = "reader"
    # what was asked
    question: str = ""
    follow_up: bool = False
    mode: str = "summary"
    filters_set: tuple[str, ...] = ()  # which filters the reader set, never their values
    # the configuration it ran with
    config_id: str = ""
    model: str | None = None
    parse_model: str | None = None
    instructions: str = ""
    package_version: str = ""
    site_version: str = ""
    experiment: str | None = None
    arm: str | None = None
    # what went in and what came out
    sources: int = 0
    spread: Mapping[str, int] | None = None  # sources per group (party, region, body)
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cache_write_long_tokens: int = 0  # of the cache writes, those to the one-hour cache
    output_tokens: int = 0
    cost_usd: float = 0.0
    stop_reason: str | None = None
    # what the checks found
    citations_total: int | None = None
    citations_invalid: int | None = None
    grounded_ratio: float | None = None
    unsupported: int | None = None
    quotes_unverified: int | None = None
    loaded_words: int | None = None
    # how long each stage took
    t_parse: int | None = None
    t_search: int | None = None
    t_rank: int | None = None
    t_sources_sent: int | None = None
    t_first_token: int | None = None
    t_written: int | None = None
    t_checked: int | None = None
    t_total: int | None = None
    # how it ended, beyond the outcome
    left_at: str | None = None  # the stage the reader left at
    error_type: str | None = None  # the exception's class name, never its message
    # what happened next, filled in later by the routes that already receive these signals
    briefing_id: str | None = None
    useful: bool | None = None
    reported: bool = False
    corrected: bool = False
    followed_up: bool = False


@dataclass(frozen=True)
class BriefingConfig:
    """The configuration a site's briefings run with, as each briefing's record names it: built once when the site
    starts (``observe.briefing_config`` works out the id and keeps the parts behind it) and given to the briefing
    desk. Every field has a name, so a misspelt one stops the site when it starts and is never recorded as empty.

    ``parse_model`` is the model that reads a question, and what the reading is priced as: None on a site whose own
    rules read every question. ``experiment`` and ``arm`` are set only while an experiment runs; the arm is then
    part of the answer cache's key. ``settings`` is everything the id was made from: never a key, a password or
    anything about a reader."""

    config_id: str
    model: str
    parse_model: str | None
    instructions: str  # the version of the site's instructions to the model
    package_version: str
    site_version: str
    experiment: str | None = None
    arm: str | None = None
    settings: Mapping[str, Any] = field(default_factory=dict)


class BriefingLog(Protocol):
    def write(self, record: BriefingRecord) -> None: ...

    def mark(self, briefing_id: str, *, useful: bool | None = None, reported: bool = False, corrected: bool = False,
             followed_up: bool = False) -> None:
        """Note what a reader did after a briefing, on that briefing's record. A later question is never linked to
        an earlier one: ``followed_up`` is a yes or no on the earlier briefing."""
        ...

    def since(self, start: datetime, end: datetime | None = None,
              kinds: Sequence[str] = ("reader",)) -> Sequence[BriefingRecord]:
        """The records from ``start`` up to but not including ``end``, oldest first, of the kinds named."""
        ...


class AnswerCache(Protocol):
    def get(self, key: str, max_hours: float) -> list[dict[str, Any]] | None: ...

    def put(self, key: str, events: list[dict[str, Any]], max_hours: float) -> None: ...
