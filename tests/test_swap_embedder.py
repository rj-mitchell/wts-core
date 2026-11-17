"""Swapping parts, second of three: the embedding model is changed, and nothing of production is.

An index is made with one embedder; the site's settings are then changed to name another (the hashing embedder at
another dimension, the recording embedder at another, and one of the same dimension under another name). What a
site's update and its search do next is played here against the real index (LanceDB) and the one in memory:

* the re-index guard refuses the new embedder: opening the index for it raises ``IndexOutOfDate``, so no vector of
  the new model is ever written beside the old model's, and no question embedded by it is searched for among them;
* search by words still works, on the index opened as it stands, so the site answers from words alone meanwhile;
* ``start_again`` throws the old vectors away and records the new embedder, and the index then serves it.

The rule behind this: a model change forces a rebuild, detected from what is stored beside the index,
never by mixing vectors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wts_core.adapters.hashing import HashingEmbedder
from wts_core.ports import Embedder, IndexMeta, IndexOutOfDate
from wts_core.testing.index import MemoryIndex, RecordingEmbedder

TEXTS = ("Weekly bin collections will continue in the borough.",
         "The council agreed the budget for adult social care.",
         "A new cycle lane was approved on the high street.")
ROWS = [{"passage_id": f"p{n}", "record_id": f"r{n}", "source_key": "k1", "heading": "", "text": text,
         "search_text": text} for n, text in enumerate(TEXTS)]
VECTOR_ROWS = [{k: row[k] for k in ("passage_id", "record_id", "source_key")} for row in ROWS]

# the embedder the index is made with, and the one the settings are changed to
SWAPS = {
    "hashing, at another dimension": (lambda: HashingEmbedder(16), lambda: HashingEmbedder(32)),
    "recording, at another dimension": (lambda: RecordingEmbedder(dimension=8), lambda: RecordingEmbedder(dimension=12)),
    "another model of the same dimension": (lambda: RecordingEmbedder(8, id="model-a@1f2e"),
                                           lambda: RecordingEmbedder(8, id="model-b@9c4d")),
}


class Lance:
    """A site's real index in a folder, opened as its code opens it."""

    def __init__(self, folder: Path) -> None:
        pytest.importorskip("lancedb")
        import pyarrow as pa

        from wts_core.adapters.lancedb import IndexSchema, LanceIndex, ScalarColumns

        text = pa.string()
        self._make = lambda embedder: LanceIndex(
            folder, embedder,
            schema=IndexSchema(filter_fields=[(n, text) for n in ("passage_id", "record_id", "source_key")],
                               passage_fields=[(n, text) for n in ("heading", "text", "search_text")]),
            scalar_columns=ScalarColumns(btree=("passage_id", "source_key", "record_id"), bitmap=()))

    def open(self, embedder: Embedder | None) -> Any:
        return self._make(embedder)

    def start_again(self, embedder: Embedder) -> Any:
        index = self.open(None)
        index.start_again(embedder)
        return self.open(embedder)


class Memory:
    """The index in memory that ships with the package's test helpers: the same guard, with no library."""

    def __init__(self, folder: Path) -> None:
        self._index: MemoryIndex | None = None

    def open(self, embedder: Embedder | None) -> Any:
        if self._index is None:
            assert embedder is not None
            self._index = MemoryIndex(embedder)
            return self._index
        return self._index if embedder is None else self._index.reopen(embedder)

    def start_again(self, embedder: Embedder) -> Any:
        """What ``start_again`` is for this index: its rows kept, its vectors thrown away, the new model recorded."""
        assert self._index is not None
        fresh = MemoryIndex(embedder)
        fresh.rows = dict(self._index.rows)
        self._index = fresh
        return fresh


@pytest.fixture(params=[Lance, Memory], ids=["the real index", "the index in memory"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    return request.param(tmp_path / "index")


@pytest.fixture(params=list(SWAPS))
def swap(request: pytest.FixtureRequest) -> tuple[Embedder, Embedder]:
    first, second = SWAPS[request.param]
    return first(), second()


def filled(store: Any, embedder: Embedder) -> Any:
    index = store.open(embedder)
    index.replace(["k1"], ROWS)
    index.add_vectors(["k1"], VECTOR_ROWS, embedder.embed_documents(list(TEXTS)))
    index.build_indexes()
    return index


def by_meaning(index: Any, embedder: Embedder, text: str = TEXTS[1]) -> list[str]:
    return [row["passage_id"] for row in index.search_meaning(embedder.embed_query(text), None, 3)]


def as_a_site_opens_it(store: Any, embedder: Embedder) -> tuple[Any, bool]:
    """What every site's search does when it starts: open the index for the embedder its settings name; if the
    index was built with another, carry on with search by words alone, and say so until the vectors are remade.
    Returns the index and whether search by meaning is on."""
    try:
        return store.open(embedder), True
    except IndexOutOfDate:
        return store.open(None), False


def test_the_index_serves_the_embedder_it_was_made_with(store, swap):
    first, _ = swap
    filled(store, first)
    index, by_meaning_on = as_a_site_opens_it(store, first)
    assert by_meaning_on and by_meaning(index, first)[0] == "p1"
    assert (index.meta.embedder_id, index.meta.dimension) == (first.id, first.dimension)


def test_the_reindex_guard_refuses_an_index_made_with_another_embedder(store, swap):
    """Changed in settings, noticed from what is stored beside the index: nothing has to remember to rebuild."""
    first, second = swap
    filled(store, first)
    with pytest.raises(IndexOutOfDate, match="rebuild it") as refused:
        store.open(second)
    stored, wanted = refused.value.stored, refused.value.wanted
    assert (stored.embedder_id, stored.dimension) == (first.id, first.dimension)
    assert (wanted.embedder_id, wanted.dimension) == (second.id, second.dimension)
    assert isinstance(stored, IndexMeta) and first.id in str(refused.value) and second.id in str(refused.value)


def test_with_the_new_embedder_refused_nothing_of_it_is_written_or_searched_by_meaning(store, swap):
    """The site carries on, on words alone. Opened as it stands the index adds no vectors; and a question the new
    model embedded is never compared with the old model's vectors."""
    first, second = swap
    filled(store, first)
    index, by_meaning_on = as_a_site_opens_it(store, second)
    assert by_meaning_on is False  # so the site's search asks for no search by meaning at all
    # its update cannot write the new model's vectors beside the old: there is no index opened for them
    with pytest.raises(IndexOutOfDate):
        store.open(second)
    if hasattr(index, "adds_vectors"):  # the real index says so outright, and refuses if asked all the same
        assert index.adds_vectors is False
        with pytest.raises(RuntimeError, match="adds no vectors"):
            index.add_vectors(["k1"], VECTOR_ROWS, second.embed_documents(list(TEXTS)))
    # Opened with the other embedder, the index refuses, always: whatever the two models' dimensions (above, and
    # again here, so that a first refusal has not quietly let the next one through).
    with pytest.raises(IndexOutOfDate):
        store.open(second)
    if second.dimension != first.dimension:
        # and a question the new model embedded is refused by either index, whoever asks: never an answer made by
        # setting one model's vector against another's
        with pytest.raises(IndexOutOfDate):
            index.search_meaning(second.embed_query(TEXTS[1]), None, 3)
        with pytest.raises(IndexOutOfDate):
            store.open(first).add_vectors(["k1"], VECTOR_ROWS, second.embed_documents(list(TEXTS)))
    else:
        # WHAT IS NOT GUARDED, held here so that it is known and not assumed (docs/EXTENDING.md, section 7): an
        # index opened as it stands, with no embedder, cannot tell which model made a vector of the right
        # length. Asked with another model's, it answers, and the answer means nothing. The guard is the open:
        # a site searches by meaning only through an index it opened WITH its embedder, as every site's does.
        assert len(index.search_meaning(second.embed_query(TEXTS[1]), None, 3)) == 3
    assert by_meaning(store.open(first), first) == by_meaning(filled_copy(first), first)  # the old vectors: untouched


def filled_copy(embedder: Embedder) -> MemoryIndex:
    index = MemoryIndex(embedder)
    index.replace(["k1"], ROWS)
    index.add_vectors(["k1"], VECTOR_ROWS, embedder.embed_documents(list(TEXTS)))
    return index


def test_search_by_words_still_works_while_the_vectors_are_out_of_date(store, swap):
    first, second = swap
    filled(store, first)
    index, _ = as_a_site_opens_it(store, second)
    found = index.search_words("cycle lane", None, 5)
    assert found and found[0]["passage_id"] == "p2" and found[0]["text"] == TEXTS[2]
    assert [row["passage_id"] for row in index.search_words("budget", None, 5)] == ["p1"]
    # and new passages can still be loaded, as the site's update loads them, to be found by their words
    index.replace(["k2"], [{**ROWS[0], "passage_id": "p9", "record_id": "r9", "source_key": "k2",
                            "text": "Parking charges were frozen.", "search_text": "Parking charges were frozen."}])
    index.build_indexes()
    assert [row["passage_id"] for row in index.search_words("parking", None, 5)] == ["p9"]


def test_starting_again_rebuilds_the_index_for_the_new_embedder(store, swap):
    first, second = swap
    filled(store, first)
    index = store.start_again(second)
    assert (index.meta.embedder_id, index.meta.dimension) == (second.id, second.dimension)
    assert index.search_meaning(second.embed_query(TEXTS[1]), None, 3) == []  # nothing until vectors are added
    assert index.search_words("cycle lane", None, 5)[0]["passage_id"] == "p2"  # the passages were kept
    index.add_vectors(["k1"], VECTOR_ROWS, second.embed_documents(list(TEXTS)))
    index.build_indexes()
    reopened, by_meaning_on = as_a_site_opens_it(store, second)
    assert by_meaning_on and by_meaning(reopened, second)[0] == "p1"
    # and now it is the old embedder that is refused: the two models' vectors were never in the index together
    with pytest.raises(IndexOutOfDate):
        store.open(first)


def test_the_two_embedders_are_embedders_and_differ_in_what_an_index_records(swap):
    first, second = swap
    assert isinstance(first, Embedder) and isinstance(second, Embedder)
    assert (first.id, first.dimension) != (second.id, second.dimension)
    assert len(list(second.embed_query("bins"))) == second.dimension


def test_an_index_whose_note_of_what_it_was_built_with_is_deleted_is_stamped_anew(tmp_path):
    """WHAT IS NOT GUARDED, the second thing (docs/EXTENDING.md, section 7): the guard is the index's own note
    (``wts_index.json``). With the note gone, an index is taken to have been built with whatever it is next
    opened with, as one made before the note existed is: only its vectors' length can still refuse. So the note
    is part of the index: it is backed up and restored with it, and never deleted to get past a refusal."""
    from wts_core.adapters.lancedb import META_FILE, stored_meta

    store = Lance(tmp_path / "index")
    first, second = RecordingEmbedder(8, id="model-a@1f2e"), RecordingEmbedder(8, id="model-b@9c4d")
    filled(store, first)
    with pytest.raises(IndexOutOfDate):
        store.open(second)
    (tmp_path / "index" / META_FILE).unlink()
    reopened = store.open(second)  # not refused: nothing says what the vectors were made with
    assert reopened.meta.embedder_id == second.id == stored_meta(tmp_path / "index").embedder_id
    with pytest.raises(IndexOutOfDate):  # and it is now the first model that is refused
        store.open(first)
    (tmp_path / "index" / META_FILE).unlink()
    with pytest.raises(IndexOutOfDate):  # a model of another length is still refused, by the table itself
        store.open(RecordingEmbedder(12, id="model-c@7a7a"))
