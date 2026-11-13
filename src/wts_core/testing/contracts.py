"""What every adapter must do, as tests: one class for each port, which an adapter's own tests subclass (ADR 0002).

A new model provider, embedding model or vector store is accepted when its adapter passes. Each class needs one
fixture, which builds the adapter::

    class TestMyIndex(VectorIndexContract):
        @pytest.fixture
        def open_index(self, tmp_path):
            return lambda embedder: MyIndex(tmp_path, embedder)

The tests never call a model or the network: a model adapter is given a script to replay (its SDK faked to say
it), from the recorded streams that ship with the package.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Self

import pytest

from wts_core.events import CitationDelta, Completed, ModelEvent, TextDelta
from wts_core.ports import Document, Embedder, IndexOutOfDate, ModelClient, ModelRequest, Usage, VectorIndex
from wts_core.testing.index import RecordingEmbedder
from wts_core.testing.models import _RECORDED, load_documents, load_stream

__all__ = ["EmbedderContract", "ModelClientContract", "ModelFactory", "Reading", "VectorIndexContract"]

SUPPORTS = frozenset({"caching", "long_cache", "fallbacks", "effort", "citations"})

# Builds a model client that will answer a briefing with this script, and a question with this object; and a
# function that says whether the stream the client opened has been closed.
type ModelFactory = Callable[[Sequence[ModelEvent], Any], tuple[ModelClient, Callable[[], bool]]]


class Reading:
    """A schema for ``structured`` that needs no outside library: Pydantic's two methods, by hand."""

    def __init__(self, search_text: str, wants_votes: bool = False) -> None:
        self.search_text, self.wants_votes = search_text, wants_votes

    @classmethod
    def model_json_schema(cls) -> dict[str, Any]:
        return {"type": "object", "properties": {"search_text": {"type": "string"},
                                                 "wants_votes": {"type": "boolean"}},
                "required": ["search_text"], "additionalProperties": False}

    @classmethod
    def model_validate(cls, obj: Any) -> Self:
        return obj if isinstance(obj, cls) else cls(**obj)


def _request(documents: tuple[Document, ...] = ()) -> ModelRequest:
    return ModelRequest(model="a-model", instructions="Use only the sources.",
                        question="What was said about the scheme?", documents=documents, effort="medium")


class ModelClientContract:
    """What ADR 0002 and 0003 promise of a model client, checked against every recorded stream.

    The fixture to give is ``model``: a ``ModelFactory``.
    """

    @pytest.fixture
    def model(self) -> ModelFactory:
        raise NotImplementedError("give a `model` fixture: see ModelFactory")

    @pytest.fixture(params=sorted(p.stem for p in _RECORDED.glob("*.jsonl")))
    def recording(self, request: pytest.FixtureRequest) -> tuple[ModelRequest, list[ModelEvent]]:
        path = _RECORDED / f"{request.param}.jsonl"
        return _request(load_documents(path)), load_stream(path)

    def test_it_says_who_it_is_and_what_it_can_do(self, model: ModelFactory,
                                                  recording: tuple[ModelRequest, list[ModelEvent]]) -> None:
        client, _ = model(recording[1], None)
        assert isinstance(client.provider, str) and client.provider
        assert client.supports <= SUPPORTS

    def test_a_stream_is_text_and_citations_then_exactly_one_completed(
            self, model: ModelFactory, recording: tuple[ModelRequest, list[ModelEvent]]) -> None:
        client, _ = model(recording[1], None)
        events = list(client.stream(recording[0]))
        assert [type(e) for e in events].count(Completed) == 1 and isinstance(events[-1], Completed)
        assert all(isinstance(e, (TextDelta, CitationDelta)) for e in events[:-1])

    def test_the_text_as_it_arrives_is_the_text_of_the_finished_blocks(
            self, model: ModelFactory, recording: tuple[ModelRequest, list[ModelEvent]]) -> None:
        client, _ = model(recording[1], None)
        events = list(client.stream(recording[0]))
        done = events[-1]
        assert isinstance(done, Completed)
        assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "".join(b.text for b in done.blocks)

    def test_every_citation_names_a_document_in_the_request(
            self, model: ModelFactory, recording: tuple[ModelRequest, list[ModelEvent]]) -> None:
        request, script = recording
        client, _ = model(script, None)
        events = list(client.stream(request))
        done = events[-1]
        assert isinstance(done, Completed)
        cited = [e.document for e in events if isinstance(e, CitationDelta)]
        cited += [c.document for b in done.blocks for c in b.citations]
        assert all(isinstance(n, int) and 0 <= n < len(request.documents) for n in cited)

    def test_closing_the_iterator_stops_the_stream(
            self, model: ModelFactory, recording: tuple[ModelRequest, list[ModelEvent]]) -> None:
        client, was_closed = model(recording[1], None)
        events = client.stream(recording[0])
        next(events)
        events.close()  # type: ignore[attr-defined]  # every adapter's stream is a generator
        assert was_closed()
        assert next(events, None) is None

    def test_token_counts_are_never_negative(
            self, model: ModelFactory, recording: tuple[ModelRequest, list[ModelEvent]]) -> None:
        client, _ = model(recording[1], None)
        done = list(client.stream(recording[0]))[-1]
        assert isinstance(done, Completed) and isinstance(done.usage, Usage)
        usage = done.usage
        assert min(usage.input_uncached, usage.cache_write, usage.cache_read, usage.output) >= 0

    def test_a_question_is_read_into_the_schema_it_is_given(
            self, model: ModelFactory, recording: tuple[ModelRequest, list[ModelEvent]]) -> None:
        client, _ = model(recording[1], {"search_text": "bin collections", "wants_votes": True})
        reading, usage = client.structured(_request(), Reading)
        assert isinstance(reading, Reading)
        assert (reading.search_text, reading.wants_votes) == ("bin collections", True)
        assert min(usage.input_uncached, usage.cache_write, usage.cache_read, usage.output) >= 0


def _row(vector: Any) -> list[float]:
    return [float(x) for x in vector]


class EmbedderContract:
    """What every embedder must do. The fixture to give is ``embedder``: the embedder."""

    TEXTS = ("The council agreed the budget.", "Weekly bin collections will continue.", "The budget was agreed.")

    @pytest.fixture
    def embedder(self) -> Embedder:
        raise NotImplementedError("give an `embedder` fixture")

    def test_it_says_what_it_is(self, embedder: Embedder) -> None:
        assert isinstance(embedder.id, str) and embedder.id
        assert isinstance(embedder.dimension, int) and embedder.dimension > 0

    def test_every_vector_has_its_dimension(self, embedder: Embedder) -> None:
        rows = embedder.embed_documents(list(self.TEXTS))
        assert len(rows) == len(self.TEXTS)
        assert all(len(_row(r)) == embedder.dimension for r in rows)
        assert len(_row(embedder.embed_query(self.TEXTS[0]))) == embedder.dimension

    def test_no_texts_give_no_vectors(self, embedder: Embedder) -> None:
        assert len(embedder.embed_documents([])) == 0

    def test_the_same_text_always_gives_the_same_vector(self, embedder: Embedder) -> None:
        first = [_row(r) for r in embedder.embed_documents(list(self.TEXTS))]
        again = [_row(r) for r in embedder.embed_documents(list(self.TEXTS))]
        alone = _row(embedder.embed_documents([self.TEXTS[1]])[0])
        assert first == again
        assert alone == pytest.approx(first[1], abs=1e-5)
        assert _row(embedder.embed_query(self.TEXTS[0])) == _row(embedder.embed_query(self.TEXTS[0]))

    def test_different_texts_give_different_vectors(self, embedder: Embedder) -> None:
        a, b = (_row(r) for r in embedder.embed_documents(list(self.TEXTS[:2])))
        assert a != b


class VectorIndexContract:
    """What every search index must do, and above all what it must refuse.

    The fixture to give is ``open_index``: a function that opens the index of this test (the same one each time it
    is called within a test) for an embedder, as a site opening its index folder does. The index must hold rows
    with the columns of ``passage`` and ``vector_row`` below.
    """

    FILTER_COLUMNS = ("passage_id", "record_id", "source_key")  # in the rows given with vectors
    PASSAGE_COLUMNS = ("heading", "text", "search_text")  # the further columns of a passage

    TEXTS = ("Weekly bin collections will continue in the borough.",
             "The council agreed the budget for adult social care.",
             "A new cycle lane was approved on the high street.")

    @pytest.fixture
    def open_index(self) -> Callable[[Embedder], VectorIndex]:
        raise NotImplementedError("give an `open_index` fixture")

    @pytest.fixture
    def embedder(self) -> RecordingEmbedder:
        return RecordingEmbedder(8)

    @staticmethod
    def passage(n: int, text: str, key: str = "k1") -> dict[str, Any]:
        return {"passage_id": f"p{n}", "record_id": f"r{n}", "source_key": key, "heading": "", "text": text,
                "search_text": text}

    @staticmethod
    def vector_row(row: Mapping[str, Any]) -> dict[str, Any]:
        return {name: row[name] for name in VectorIndexContract.FILTER_COLUMNS}

    def filled(self, open_index: Callable[[Embedder], VectorIndex], embedder: Embedder) -> VectorIndex:
        index = open_index(embedder)
        rows = [self.passage(n, text) for n, text in enumerate(self.TEXTS)]
        index.replace(["k1"], rows)
        index.add_vectors(["k1"], [self.vector_row(r) for r in rows], embedder.embed_documents(list(self.TEXTS)))
        index.build_indexes()
        return index

    def ids_by_meaning(self, index: VectorIndex, embedder: Embedder) -> list[str]:
        return sorted(r["passage_id"] for r in index.search_meaning(embedder.embed_query("anything"), None, 50))

    def test_it_says_what_it_was_built_with(self, open_index: Callable[[Embedder], VectorIndex],
                                            embedder: RecordingEmbedder) -> None:
        meta = open_index(embedder).meta
        assert (meta.embedder_id, meta.dimension) == (embedder.id, embedder.dimension)

    def test_search_by_words_finds_a_passage_by_its_words(self, open_index: Callable[[Embedder], VectorIndex],
                                                          embedder: RecordingEmbedder) -> None:
        index = self.filled(open_index, embedder)
        found = index.search_words("cycle lane", None, 5)
        assert found and found[0]["passage_id"] == "p2" and found[0]["text"] == self.TEXTS[2]
        assert index.search_words("zebra", None, 5) == []

    def test_search_by_meaning_puts_the_nearest_first(self, open_index: Callable[[Embedder], VectorIndex],
                                                      embedder: RecordingEmbedder) -> None:
        index = self.filled(open_index, embedder)
        found = index.search_meaning(embedder.embed_query(self.TEXTS[1]), None, 3)
        assert [r["passage_id"] for r in found][0] == "p1" and len(found) == 3
        distances = [r["_distance"] for r in found]
        assert distances == sorted(distances) and distances[0] == pytest.approx(0.0, abs=1e-3)
        assert len(index.search_meaning(embedder.embed_query(self.TEXTS[1]), None, 1)) == 1

    def test_rows_and_vectors_replace_those_with_the_same_key(self, open_index: Callable[[Embedder], VectorIndex],
                                                               embedder: RecordingEmbedder) -> None:
        index = self.filled(open_index, embedder)
        new = self.passage(7, "Parking charges were frozen for a year.")
        other = self.passage(8, "The library will open on Sundays.", key="k2")
        index.replace(["k1"], [new])
        index.replace(["k2"], [other])
        assert self.ids_by_meaning(index, embedder) == []  # the old passages' vectors went with them
        index.add_vectors(["k1"], [self.vector_row(new)], embedder.embed_documents([new["text"]]))
        index.add_vectors(["k2"], [self.vector_row(other)], embedder.embed_documents([other["text"]]))
        index.add_vectors(["k1"], [self.vector_row(new)], embedder.embed_documents([new["text"]]))  # again: no copy
        index.build_indexes()
        assert self.ids_by_meaning(index, embedder) == ["p7", "p8"]
        assert [r["passage_id"] for r in index.search_words("parking charges", None, 5)] == ["p7"]
        assert index.search_words("cycle lane", None, 5) == []
        assert [r["passage_id"] for r in index.search_words("library", None, 5)] == ["p8"]

    def test_tidying_loses_nothing(self, open_index: Callable[[Embedder], VectorIndex],
                                   embedder: RecordingEmbedder) -> None:
        index = self.filled(open_index, embedder)
        index.tidy()
        assert self.ids_by_meaning(index, embedder) == ["p0", "p1", "p2"]
        assert index.search_words("budget", None, 5)[0]["passage_id"] == "p1"

    def test_it_opens_again_for_the_embedder_it_was_built_with(self, open_index: Callable[[Embedder], VectorIndex],
                                                               embedder: RecordingEmbedder) -> None:
        self.filled(open_index, embedder)
        again = open_index(RecordingEmbedder(embedder.dimension))
        assert self.ids_by_meaning(again, embedder) == ["p0", "p1", "p2"]

    def test_an_embedder_with_another_id_is_refused(self, open_index: Callable[[Embedder], VectorIndex],
                                                    embedder: RecordingEmbedder) -> None:
        self.filled(open_index, embedder)
        other = RecordingEmbedder(embedder.dimension, id="another-model")
        with pytest.raises(IndexOutOfDate) as refused:
            open_index(other)
        assert refused.value.stored.embedder_id == embedder.id and refused.value.wanted.embedder_id == other.id

    def test_an_embedder_with_another_dimension_is_refused(self, open_index: Callable[[Embedder], VectorIndex],
                                                           embedder: RecordingEmbedder) -> None:
        self.filled(open_index, embedder)
        with pytest.raises(IndexOutOfDate):
            open_index(RecordingEmbedder(embedder.dimension * 2, id=embedder.id))

    def test_vectors_from_two_embedders_are_never_mixed(self, open_index: Callable[[Embedder], VectorIndex],
                                                        embedder: RecordingEmbedder) -> None:
        index = self.filled(open_index, embedder)
        wide = RecordingEmbedder(embedder.dimension * 2)
        row = self.passage(9, "Vectors of another model.", key="k9")
        with pytest.raises(IndexOutOfDate):
            index.add_vectors(["k9"], [self.vector_row(row)], wide.embed_documents([row["text"]]))
        with pytest.raises(IndexOutOfDate):
            open_index(RecordingEmbedder(embedder.dimension, id="another-model"))
        # nothing was added and nothing lost: the index is as its own embedder left it
        assert self.ids_by_meaning(open_index(embedder), embedder) == ["p0", "p1", "p2"]
