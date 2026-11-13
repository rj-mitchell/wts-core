"""The pipeline: everything that follows this site's own record. It reads a question, finds the minutes that bear
on it, has the model write a briefing from them, and puts the model's words through the checks.

The package runs the flow around this (limits, caps, the cache, the record: ``wts_core.briefing``); what happens
inside is the site's. ``Pipeline.write`` and ``Pipeline.sources_only`` are the two functions the site's route gives
the briefing desk in an ``Ask``. Each sends the events a reader receives, in the family's order: the ``plan`` (how
the question was read), the ``sources`` (always before any text), the text and citations as they are written, and
a ``final`` event with the checked briefing.

The model, the embedder and the index are passed in as the package's interfaces (``wts_core.ports``), so the same
pipeline runs over the real ones or over the fakes in ``wts_core.testing``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from wts_core.adapters import anthropic, model_client
from wts_core.adapters.hashing import HashingEmbedder
from wts_core.briefing import Event, Stage, current_stages
from wts_core.checks import blend, check_briefing, round_robin
from wts_core.events import Answer, Block, Completed, blocks_as_today, to_reader
from wts_core.observe import SqliteBriefingLog, briefing_config
from wts_core.ports import (
    BriefingConfig,
    Document,
    Embedder,
    ModelClient,
    ModelRequest,
    SpendingRecord,
    Usage,
    VectorIndex,
)
from wts_core.settings import SettingsError
from wts_core.testing.index import MemoryIndex
from wts_core.testing.models import ScriptedModel, load_header

from parks.site import LOADED_WORDS, MESSAGES, NO_MODEL, NO_RECORDS, SITE, VERIFIER, ParksSettings

__all__ = ["Minute", "Pipeline", "Reading", "Source", "configuration", "data_stamp", "embedder_from_settings",
           "load_minutes", "model_from_settings", "new_index", "read_by_rules", "scripted_model"]

# ---- the record --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Minute:
    """One item of one meeting's minutes: the unit this site's record is made of."""

    id: str
    park: str
    committee: str
    date: str
    item: str
    title: str
    url: str
    passages: tuple[str, ...]


def load_minutes(path: Path) -> list[Minute]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Minute(**{**m, "passages": tuple(m["passages"])}) for m in raw["minutes"]]


def data_stamp(path: Path) -> str:
    """A stamp of the record as it stands: part of the answer cache's key, so that an answer written from older
    minutes is never served once the record has changed."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


@dataclass(frozen=True)
class Source:
    """One minute as the model is given it and the reader is shown it, numbered from 1. It is what the checks read
    too (``wts_core.checks.TitledSource``: ``n``, ``title``, ``blocks``, ``meta``)."""

    n: int
    title: str
    url: str
    blocks: tuple[str, ...]  # its citable text, word for word from the minutes
    meta: Mapping[str, Any] = field(default_factory=dict)

    def document(self) -> Document:
        return Document(number=self.n, title=self.title, source=self.url, passages=self.blocks)

    def card(self) -> dict[str, Any]:
        """What the reader is shown of it, in the ``sources`` event."""
        return {"n": self.n, "title": self.title, "url": self.url, **self.meta}


def _source(n: int, minute: Minute) -> Source:
    day = date.fromisoformat(minute.date)
    title = f"Minutes of the {minute.committee}, {day.day} {day:%B %Y}: item {minute.item}, {minute.title}"
    return Source(n, title, minute.url, minute.passages,
                  {"id": minute.id, "park": minute.park, "date": minute.date})


# ---- reading a question ------------------------------------------------------------------------------------------


class Reading(BaseModel):
    """How a question was read: the words to search the minutes for, and the park if the question names one. The
    model fills this in (``ModelClient.structured``); so do the site's own rules, which cost nothing."""

    topic: str
    park: str | None = None


READING_INSTRUCTIONS = (
    "You read questions about the minutes of park committees. Give the few words to search the minutes for "
    "(topic), and the park's name if the question is about one park (park), else nothing. Add no words of your own."
)

_WORD = re.compile(r"[a-z0-9]+")
_NOT_TOPIC = frozenset(_WORD.findall(
    "a about all an and any are at been by can committee committees decided did do does for from has have how in "
    "is it its of on or park parks said say that the their there they this to was were what when where which who "
    "why will with"))


def read_by_rules(question: str, parks: Sequence[str]) -> Reading:
    """The site's own reading, with no model: the question's words without the common ones, and a park if the
    question names one. Used when the model may not be asked (a limit has been reached, or there is no model),
    and when it fails."""
    lowered = question.lower()
    park = next((p for p in parks if p.lower() in lowered), None)
    in_park_name = set(_WORD.findall(park.lower())) if park else set()
    words = [w for w in _WORD.findall(lowered) if w not in _NOT_TOPIC and w not in in_park_name]
    return Reading(topic=" ".join(dict.fromkeys(words)), park=park)


# ---- the instructions to the model -------------------------------------------------------------------------------

# Change these and raise SITE.instructions_version with them.
INSTRUCTIONS = (
    "You write short, neutral briefings on what park committees have decided, in British English, for readers who "
    "will check every claim. Use only the minutes you are given: every factual sentence must be supported by a "
    "citation of the words in a minute. Begin each point with the park's name. Report in neutral words: no "
    "judgement of your own on a park, a committee or a decision. Add no background knowledge. If the minutes do "
    f'not answer the question, reply with exactly this and nothing else: "{NO_RECORDS}"'
)


# ---- the pipeline ------------------------------------------------------------------------------------------------


def _reached(stage: Stage) -> None:
    """A stage of the briefing being written has just been reached. The briefing desk can see for itself when the
    question was read, the sources sent and the first words written; the search, the ranking and the model
    finishing happen in here, so the pipeline marks them. The desk times them, puts them in the briefing's record
    and writes them to the structured log."""
    current_stages().mark(stage)


# given what the model was sent and what it wrote back: how a caller keeps a briefing as a fixture for replay
type Keep = Callable[[tuple[Document, ...], tuple[Block, ...]], None]


class Pipeline:
    """Where Parks Stand's pipeline over a model, an embedder and an index. ``model`` is ``None`` when there is no
    model to ask: the site then shows the minutes it found and writes no briefing. ``spending`` is where the one
    model call the briefing desk cannot see is recorded (see ``sources_only``)."""

    def __init__(self, settings: ParksSettings, *, model: ModelClient | None, embedder: Embedder,
                 index: VectorIndex, spending: SpendingRecord | None = None) -> None:
        self.settings = settings
        self.model = model
        self.embedder = embedder
        self.index = index
        self.spending = spending
        self.minutes = {m.id: m for m in load_minutes(settings.minutes_file)}
        self.parks = sorted({m.park for m in self.minutes.values()})
        self.records_up_to = max(m.date for m in self.minutes.values())
        self._fill_index()

    @property
    def has_model(self) -> bool:
        return self.model is not None

    def _fill_index(self) -> None:
        """Put the record in the index: one row a minute, searchable by its words and by its meaning. A real site
        does this in its nightly update, not when it starts."""
        rows = [{"passage_id": m.id, "source_key": m.id, "park": m.park,
                 "search_text": " ".join((m.title, m.park, *m.passages))} for m in self.minutes.values()]
        keys = [row["source_key"] for row in rows]
        self.index.replace(keys, rows)
        self.index.add_vectors(keys, rows, self.embedder.embed_documents([row["search_text"] for row in rows]))
        self.index.build_indexes()

    # ---- reading and finding: free unless the model reads the question -----------------------------------------

    def read(self, question: str, park: str | None, *, free: bool) -> tuple[Reading, Usage | None, str | None]:
        """How the question is read, what the reading cost (``None``: nothing), and the error if the model was
        asked and failed. ``park`` is the reader's own choice of park, which always stands."""
        by_rules = read_by_rules(question, self.parks)
        if park:
            by_rules = by_rules.model_copy(update={"park": park})
        if free or self.model is None:
            return by_rules, None, None
        answer = self.settings.answer
        request = ModelRequest(model=answer["query_parse_model"], instructions=READING_INSTRUCTIONS,
                               question=question, max_tokens=500, effort=answer["query_parse_effort"])
        try:
            reading, usage = self.model.structured(request, Reading)
        except Exception as exc:  # a bad key, a refusal: the site's own rules read it instead
            return by_rules, None, f"{type(exc).__name__}: {exc}"
        return (reading.model_copy(update={"park": park}) if park else reading), usage, None

    def find(self, reading: Reading, mode: str) -> tuple[list[Source], int]:
        """The minutes that bear on a question, numbered, and how many were candidates. Free: no model call.

        The search by words finds the candidates; the search by meaning helps to order them. No park is given more
        than its share. The model is given the chosen minutes oldest first, as the record runs.
        """
        ranking = self.settings.ranking
        everything = len(self.minutes)
        # A real index takes a filter as its ``where`` clause; a dozen minutes are filtered here.
        found = [row for row in self.index.search_words(reading.topic, None, everything)
                 if reading.park is None or row["park"] == reading.park] if reading.topic else []
        meaning = {row["passage_id"]: 1.0 - row["_distance"] for row in
                   self.index.search_meaning(self.embedder.embed_query(reading.topic), None, everything)} \
            if found else {}
        _reached("searched")
        scores = blend([row["_score"] for row in found], [meaning.get(row["passage_id"]) for row in found],
                       word_weight=float(ranking["word_weight"]), meaning_floor=float(ranking["meaning_floor"]),
                       meaning_ceiling=float(ranking["meaning_ceiling"]))
        pool = sorted(({**row, "_relevance": score} for row, score in zip(found, scores, strict=True)),
                      key=lambda row: (-row["_relevance"], row["passage_id"]))
        limit = int(self.settings.answer["comprehensive_sources" if mode == "comprehensive" else "summary_sources"])
        chosen = round_robin(pool, limit, group_of=lambda row: str(row["park"]),
                             key_of=lambda row: str(row["passage_id"]), score_of=lambda row: float(row["_relevance"]),
                             caps=((lambda row: str(row["park"]), int(ranking["max_per_park"])),))
        _reached("ranked")
        minutes = sorted((self.minutes[row["passage_id"]] for row in chosen), key=lambda m: (m.date, m.id))
        return [_source(n, minute) for n, minute in enumerate(minutes, start=1)], len(found)

    # ---- the two functions the briefing desk is given ----------------------------------------------------------

    def write(self, question: str, *, mode: str = "summary", park: str | None = None,
              keep: Keep | None = None) -> Iterator[Event]:
        """Write a briefing: the events a reader is sent. The desk records what the ``plan`` and ``final`` events
        say was spent, saves the briefing and keeps the record; this only does the site's part."""
        reading, read_usage, read_error = self.read(question, park, free=False)
        plan: Event = {"type": "plan", "plan": self._plan(reading, by_model=read_usage is not None),
                       "usage": read_usage.as_stored() if read_usage else None}
        if read_error:
            plan["parse_error"] = read_error  # the desk notes it for the owner and takes it out of the event
        yield plan

        sources, candidates = self.find(reading, mode)
        yield {"type": "sources", "sources": [s.card() for s in sources], "candidates": candidates, "semantic": True}
        if not sources:
            yield {"type": "final", "answer": self._nothing_found(), "usage": None}
            return
        if self.model is None:
            yield {"type": "final", "answer": None, "usage": None, "note": NO_MODEL}
            return

        answer = self.settings.answer
        request = ModelRequest(
            model=answer["model"], instructions=INSTRUCTIONS, question=question,
            documents=tuple(s.document() for s in sources), max_tokens=int(answer["max_tokens"]),
            effort=answer["comprehensive_effort" if mode == "comprehensive" else "summary_effort"],
            fallbacks=bool(answer["use_fallbacks"]))
        done: Completed | None = None
        stream = self.model.stream(request)
        try:
            for event in stream:
                if isinstance(event, Completed):
                    done = event
                else:
                    yield dict(to_reader(event))  # text and citations, as they are written
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()  # if the reader has gone, this stops the model: nothing more is written or paid for
        _reached("written")
        if done is None:
            raise RuntimeError("the model returned no answer")
        if done.stop_reason == "refusal":
            # An error for the reader, never an empty briefing saved and shown as fully grounded. The call was
            # still paid for, so its token counts go with the event: the desk records them and does not send them.
            yield {"type": "error", "message": MESSAGES.model_declined, "usage": done.usage.as_stored(),
                   "model": done.model}
            return
        # every check, in the family's one order: citations, preambles, spelling, loaded words, quotations
        report = check_briefing(blocks_as_today(done), sources, VERIFIER, LOADED_WORDS)
        if keep is not None:
            keep(request.documents, done.blocks)
        yield {"type": "final", "answer": report, "usage": done.usage.as_stored(), "model": done.model,
               "stop_reason": done.stop_reason}

    def sources_only(self, question: str, note: str, *, free: bool, mode: str = "summary", park: str | None = None,
                     visitor: str | None = None) -> Iterator[Event]:
        """Find the minutes and write no briefing, ending with the desk's ``note`` for the reader. ``free`` is true
        when a limit or a cap stopped the briefing: the question must then cost nothing to read."""
        reading, read_usage, _ = self.read(question, park, free=free)
        if read_usage is not None and self.spending is not None:
            # These events carry no token counts, so the desk cannot see this call. The site records the spending
            # itself, and tells the briefing's record what it cost.
            cost = self.spending.add("parse", self.settings.answer["query_parse_model"], read_usage, visitor=visitor)
            current_stages().spent(read_usage, cost)
        yield {"type": "plan", "plan": self._plan(reading, by_model=read_usage is not None), "usage": None}
        sources, candidates = self.find(reading, mode)
        yield {"type": "sources", "sources": [s.card() for s in sources], "candidates": candidates, "semantic": True}
        yield {"type": "final", "answer": None, "usage": None, "note": note}

    # ---- small parts ---------------------------------------------------------------------------------------------

    @staticmethod
    def _plan(reading: Reading, *, by_model: bool) -> dict[str, Any]:
        return {**reading.model_dump(), "read_by": "model" if by_model else "rules"}

    @staticmethod
    def _nothing_found() -> Answer:
        """The briefing when no minute bears on the question: the "no records" words, through the same checks, so
        it has the shape of any other. No model is asked."""
        return check_briefing([{"text": NO_RECORDS, "citations": []}], [], VERIFIER, LOADED_WORDS)


# ---- the model, the embedder and the index, from settings --------------------------------------------------------


def scripted_model(recording: Path) -> ModelClient:
    """A model that replays one recorded briefing, whatever it is asked: the package's ``ScriptedModel`` over a
    recording made for this site (``scripts/make_recordings.py``). The recording's header also holds how the model
    read the question it was made for, which is how this model reads every question."""
    header = load_header(recording)
    return ScriptedModel(recording, structured=header.get("reading"),
                         structured_usage=Usage(**header.get("reading_usage", {})))


def model_from_settings(settings: ParksSettings, env: Mapping[str, str] | None = None) -> ModelClient | None:
    """The model ``[answer] provider`` names, or ``None`` when there is nothing to call one with. Made once and
    kept for the life of the process."""
    provider = str(settings.answer["provider"]).strip().lower()
    if provider == "scripted":
        return scripted_model(settings.recordings_dir / f"{settings.answer['recording']}.jsonl")
    if provider == "anthropic" and not anthropic.has_credentials(SITE, settings, env):
        return None  # no key: the site shows the minutes only
    return model_client(settings, SITE, env)


def embedder_from_settings(settings: ParksSettings) -> Embedder:
    embedding = settings.section("embedding")
    if embedding["backend"] == "hashing":
        return HashingEmbedder(int(embedding["dim"]))
    raise SettingsError(f"{settings.config_path}: [embedding] backend is {embedding['backend']!r}; this example "
                        'has only "hashing". A real site names wts_core.adapters.fastembed.FastEmbedEmbedder here')


def new_index(embedder: Embedder) -> VectorIndex:
    """An index held in memory: a dozen minutes need no more. A real site opens
    ``wts_core.adapters.lancedb.LanceIndex`` on a folder under its data folder instead."""
    return MemoryIndex(embedder)


# ---- the configuration, for the record of each briefing ----------------------------------------------------------


def configuration(settings: ParksSettings, embedder: Embedder, log: SqliteBriefingLog | None) -> BriefingConfig:
    """Everything that could change a briefing, and the short id of it all: what the briefing desk writes into each
    briefing's record and what an evaluation run is filed under, so a figure can be compared before and after a
    change. Never a key, and nothing about a reader. Given the record of briefings, the same call keeps the
    settings behind the id there; ``None`` (an evaluation run, which keeps no record) only works the id out."""
    answer = settings.answer
    return briefing_config(
        log=log, model=answer["model"], parse_model=answer["query_parse_model"],
        instructions=SITE.instructions_version, site_version=SITE.version,
        also={"provider": answer["provider"], "embedder": embedder.id, "ranking": dict(settings.ranking),
              "sources": {"summary": answer["summary_sources"], "comprehensive": answer["comprehensive_sources"]}})
