"""The recording embedder and the index in memory: they pass the contracts the real adapters pass, and they keep a
note of everything they are given."""

from __future__ import annotations

import math

import pytest

from wts_core.ports import Embedder, IndexMeta, IndexOutOfDate, VectorIndex
from wts_core.testing.contracts import EmbedderContract, VectorIndexContract
from wts_core.testing.index import MemoryIndex, RecordingEmbedder


class TestRecordingEmbedder(EmbedderContract):
    @pytest.fixture(params=[8, 32])
    def embedder(self, request):
        return RecordingEmbedder(request.param)


class TestMemoryIndex(VectorIndexContract):
    @pytest.fixture
    def open_index(self):
        opened: list[MemoryIndex] = []

        def open_(embedder):
            opened.append(opened[0].reopen(embedder) if opened else MemoryIndex(embedder))
            return opened[-1]

        return open_


def test_the_embedder_records_every_text_it_is_given():
    e = RecordingEmbedder()
    assert isinstance(e, Embedder) and (e.id, e.dimension) == ("recording-8", 8)
    e.embed_documents(["first passage", "second passage"])
    e.embed_query("a question")
    e.embed_documents([])
    assert e.documents == ["first passage", "second passage"] and e.queries == ["a question"]
    assert e.texts == ["first passage", "second passage", "a question"]
    assert RecordingEmbedder(4, id="named").id == "named"


def test_its_vectors_are_plain_lists_of_length_one_that_depend_only_on_the_words():
    e = RecordingEmbedder(16)
    a, b, c = e.embed_documents(["The budget was agreed", "agreed: the BUDGET was!", "cycle lanes"])
    assert isinstance(a, list) and a == b != c
    assert math.sqrt(sum(x * x for x in a)) == pytest.approx(1.0)
    assert e.embed_query("") == [0.0] * 16  # no words: noughts, not a division by nought


def rows(*texts: str, key: str = "k1") -> list[dict]:
    return [VectorIndexContract.passage(n, text, key) for n, text in enumerate(texts)]


def test_the_index_records_everything_added_and_every_call():
    e = RecordingEmbedder()
    index: VectorIndex = MemoryIndex(e)
    assert isinstance(index, MemoryIndex) and index.meta == IndexMeta("recording-8", 8)
    first = rows("bins are collected weekly", "the budget was agreed")
    index.replace(["k1"], first)
    index.add_vectors(["k1"], first, e.embed_documents([r["text"] for r in first]))
    index.replace(["k1"], rows("parking charges are frozen"))
    index.build_indexes(), index.tidy()
    assert index.calls == ["replace", "add_vectors", "replace", "build_indexes", "tidy"]
    assert list(index.rows) == ["p0"] and index.vectors == {}  # replaced, and the old vectors went with the passages
    # but what was ever written is all still in `added`: a test can say what never reached the index
    assert [r["text"] for r in index.added if "vector" not in r] == \
        ["bins are collected weekly", "the budget was agreed", "parking charges are frozen"]
    assert sum("vector" in r for r in index.added) == 2
    assert not any("statement" in str(r) for r in index.added)


def test_a_where_clause_is_kept_and_applied_only_if_the_test_says_how():
    e = RecordingEmbedder()
    data = rows("bins in the north", key="k1") + [VectorIndexContract.passage(5, "bins in the south", "k2")]
    plain = MemoryIndex(e)
    plain.replace([], data)
    assert len(plain.search_words("bins", "source_key = 'k2'", 5)) == 2  # the fake cannot read SQL
    assert plain.wheres == ["source_key = 'k2'"]
    told = MemoryIndex(e, matches=lambda where, row: f"'{row['source_key']}'" in where)
    told.replace([], data)
    told.add_vectors([], data, e.embed_documents([r["text"] for r in data]))
    assert [r["passage_id"] for r in told.search_words("bins", "source_key = 'k2'", 5)] == ["p5"]
    assert [r["passage_id"] for r in told.search_meaning(e.embed_query("bins"), "source_key = 'k1'", 5)] == ["p0"]
    assert len(told.search_meaning(e.embed_query("bins"), None, 5)) == 2


def test_search_by_words_ranks_by_how_many_words_match_and_search_by_meaning_by_distance():
    e = RecordingEmbedder(32)
    index = MemoryIndex(e)
    data = rows("the budget", "the budget for social care", "cycle lanes")
    index.replace([], data)
    index.add_vectors([], data, e.embed_documents([r["text"] for r in data]))
    found = index.search_words("budget social care", None, 5)
    assert [(r["passage_id"], r["_score"]) for r in found] == [("p1", 3.0), ("p0", 1.0)]
    assert index.search_words("budget", None, 1)[0]["passage_id"] in ("p0", "p1") and index.search_words("", None, 5) == []
    near = index.search_meaning(e.embed_query("cycle lanes"), None, 3)
    assert near[0]["passage_id"] == "p2" and near[0]["_distance"] == pytest.approx(0.0, abs=1e-9)
    assert "vector" not in near[0] and near[0]["source_key"] == "k1"


def test_reopening_shares_what_is_stored_and_refuses_another_embedder():
    e = RecordingEmbedder()
    index = MemoryIndex(e)
    index.replace([], rows("bins"))
    again = index.reopen(IndexMeta("recording-8", 8))
    again.replace(["k9"], [VectorIndexContract.passage(9, "libraries", "k9")])
    assert set(index.rows) == {"p0", "p9"} and index.calls == again.calls
    with pytest.raises(IndexOutOfDate):
        index.reopen(RecordingEmbedder(8, id="another-model"))
    with pytest.raises(IndexOutOfDate):
        index.search_meaning([0.0] * 4, None, 5)
    with pytest.raises(ValueError, match="1 rows and 2 vectors"):
        index.add_vectors([], rows("bins"), e.embed_documents(["a", "b"]))
