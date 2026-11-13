"""The search index: the contract, the sites' own tests for the part they shared, parity with each site's copy, and
what is new: the index keeps what it was built with beside it, and refuses anything else."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import numpy as np
import pyarrow as pa
import pytest

from adapters_sites import SITES, site_file
from wts_core.adapters.hashing import HashingEmbedder
from wts_core.adapters.lancedb import (
    KEEP_OLD_VERSIONS,
    META_FILE,
    TRAINED_FILE,
    IndexSchema,
    LanceIndex,
    ScalarColumns,
    date_lit,
    retry_once,
    sanitise_query,
    sql_list,
    sql_str,
    stored_meta,
    vector_index_due,
)
from wts_core.ports import IndexMeta, IndexOutOfDate, VectorIndex
from wts_core.testing.contracts import VectorIndexContract
from wts_core.testing.index import RecordingEmbedder

DIM = 16

# ---- each site's columns, as its index/lance.py has them --------------------------------------------------------

S, D, I, B, L = pa.string(), pa.date32(), pa.int32(), pa.bool_(), pa.list_(pa.string())  # noqa: E741

MPS = (
    IndexSchema(
        filter_fields=[("passage_id", S), ("record_id", S), ("source", S), ("source_key", S), ("record_type", S),
                       ("house", S), ("date", D), ("year", I), ("person_id", S), ("party_id", S), ("region", S),
                       ("is_gov", B), ("is_shadow", B), ("is_chair", B), ("gov_portfolios", L),
                       ("shadow_portfolios", L), ("chair_portfolios", L)],
        passage_fields=[("chunk", I), ("chamber", S), ("speaker_name", S), ("party", S), ("constituency", S),
                        ("member_house", S), ("heading", S), ("text", S), ("search_text", S)]),
    ScalarColumns(btree=("passage_id", "source_key", "record_id", "person_id", "date"),
                  bitmap=("source", "house", "record_type", "region", "party_id", "is_gov", "is_shadow", "is_chair",
                          "year"),
                  label_list=("gov_portfolios", "shadow_portfolios", "chair_portfolios")),
    "float16",
)
COUNTRIES = (
    IndexSchema(
        filter_fields=[("passage_id", S), ("record_id", S), ("source", S), ("source_key", S), ("body", S),
                       ("date", D), ("year", I), ("country_code", S), ("entity_kind", S), ("speaker_role", S),
                       ("participant", S), ("group_statement", B), ("groups", L)],
        passage_fields=[("chunk", I), ("speaker_name", S), ("country_name", S), ("on_behalf_of", S), ("symbol", S),
                        ("heading", S), ("text", S), ("search_text", S)]),
    ScalarColumns(btree=("passage_id", "source_key", "record_id", "country_code", "date"),
                  bitmap=("source", "body", "entity_kind", "speaker_role", "participant", "group_statement", "year")),
    "float32",
)
COUNCILS = (
    IndexSchema(
        filter_fields=[("passage_id", S), ("record_id", S), ("source_key", S), ("gss", S), ("nation", S),
                       ("council_type", S), ("region", S), ("kind", S), ("date", D), ("year", I), ("control", S),
                       ("parties", L), ("members", L), ("named_vote", B)],
        passage_fields=[("chunk", I), ("council_name", S), ("committee", S), ("item_title", S), ("item_number", S),
                        ("heading", S), ("text", S), ("search_text", S), ("url", S)]),
    ScalarColumns(btree=("passage_id", "source_key", "record_id", "gss", "date"),
                  bitmap=("nation", "council_type", "region", "kind", "control", "named_vote", "year")),
    "float32",
)
SHAPES = {"mps": MPS, "countries": COUNTRIES, "councils": COUNCILS}

WORDS = ["budget", "bins", "housing", "transport", "schools", "libraries", "parks", "planning", "climate", "roads"]


def blank(kind: pa.DataType) -> Any:
    if kind == D:
        return date(2026, 1, 1)
    return {S: "", I: 2026, B: False}.get(kind, [])


def passage(schema: IndexSchema, n: int, per_key: int = 10) -> dict[str, Any]:
    """Row ``n`` of a site's shape: every column filled, ``k<n // per_key>`` its source key."""
    row = {name: blank(kind) for name, kind in [*schema.filter_fields, *schema.passage_fields]}
    text = f"Passage {n} about {WORDS[n % len(WORDS)]} and number{n}."
    row.update(passage_id=f"p{n}", record_id=f"r{n}", source_key=f"k{n // per_key}", heading=f"Heading {n}",
               text=text, search_text=f"Heading {n}\n{text}", chunk=0)
    return row


def passages(schema: IndexSchema, n: int, start: int = 0, per_key: int = 10) -> list[dict[str, Any]]:
    return [passage(schema, i, per_key) for i in range(start, start + n)]


def vectors(n: int, seed: int = 0, dim: int = DIM) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal((n, dim)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


@pytest.fixture(params=list(SHAPES))
def shape(request):
    return SHAPES[request.param]


def open_index(path, shape, embedder: Any = "default", **more: Any) -> LanceIndex:
    schema, scalar, number_type = shape
    embedder = HashingEmbedder(DIM) if isinstance(embedder, str) else embedder
    return LanceIndex(path, embedder, schema=schema, scalar_columns=scalar, number_type=number_type, **more)


def vector_type(index: LanceIndex) -> pa.DataType:
    return index.vectors().schema.field("vector").type.value_type


# --------------------------------------------------------------------------- the contract every index passes

MINIMAL = IndexSchema(filter_fields=[(name, S) for name in VectorIndexContract.FILTER_COLUMNS],
                      passage_fields=[(name, S) for name in VectorIndexContract.PASSAGE_COLUMNS])
MINIMAL_SCALARS = ScalarColumns(btree=("passage_id", "source_key", "record_id"), bitmap=())


class TestLanceIndex(VectorIndexContract):
    @pytest.fixture(params=["float32", "float16"])
    def open_index(self, tmp_path, request):
        return lambda embedder: LanceIndex(tmp_path, embedder, schema=MINIMAL, scalar_columns=MINIMAL_SCALARS,
                                           number_type=request.param)


def test_it_is_a_vector_index(tmp_path):
    index: VectorIndex = open_index(tmp_path, COUNCILS)
    assert index.meta == IndexMeta("hashing-16", 16, "float32", 1)


# --------------------------------------------------------------------------- the sites' own tests of the base


def test_the_words_of_a_question_are_never_read_as_query_syntax():
    assert sanitise_query('"trial by jury" AND (courts) title:x -not +must ~2 a/b <c> d=e f|g h&i') == \
        "trial by jury AND courts title x not must 2 a b c d e f g h i"
    assert sanitise_query("") == "" and sanitise_query(None) == ""  # type: ignore[arg-type]
    assert sanitise_query("O'Brien's   motion?!") == "O Brien s motion"


def test_where_clause_escapes_values():
    assert sql_str("O'Brien land") == "'O''Brien land'"
    assert sql_list(["region:africa", "it's"]) == "['region:africa', 'it''s']"
    assert date_lit(date(2020, 1, 1)) == "DATE '2020-01-01'"


def test_superseded_versions_are_kept_for_an_hour():
    assert timedelta(hours=1) == KEEP_OLD_VERSIONS


def test_a_search_that_fails_once_is_tried_again():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise OSError("Not found: vectors.lance/data/x.lance")
        return ["ok"]

    assert retry_once(flaky) == ["ok"] and len(calls) == 2


def test_vector_index_due():
    n = 10_000
    assert not vector_index_due(n - 1, None, False)          # too few to be worth an index
    assert vector_index_due(n, None, False)                  # first build
    assert vector_index_due(n, None, True)                   # built before its size was recorded
    assert not vector_index_due(int(n * 1.2), n, True)       # merged in
    assert vector_index_due(int(n * 1.2) + 1, n, True)       # grown by more than a fifth
    assert vector_index_due(n, n, False)                     # the index has gone
    assert vector_index_due(121, 100, True, minimum=1) and not vector_index_due(120, 100, True, minimum=1)


def _level(code: str, **env: str) -> str:
    base = {k: v for k, v in os.environ.items() if k != "LANCEDB_LOG"}
    out = subprocess.run([sys.executable, "-c", code], env={**base, **env}, capture_output=True, text=True, check=True)
    return out.stdout.strip()


OPEN = ("import os, sys, tempfile; from wts_core.adapters.lancedb import LanceIndex, IndexSchema, ScalarColumns; "
        "assert 'lancedb' not in sys.modules; "
        "LanceIndex(tempfile.mkdtemp(), None, schema=IndexSchema([], []), scalar_columns=ScalarColumns((), ())); "
        "print(os.environ.get('LANCEDB_LOG'))")


def test_lancedb_logs_only_errors_unless_told_otherwise():
    """LanceDB warns once per cluster while the vector index is small, which filled the update logs. It reads
    LANCEDB_LOG once, when it is first imported, so the level is set before that; checked in a fresh interpreter."""
    assert _level(OPEN) == "error"


def test_an_explicit_lancedb_log_level_is_kept():
    assert _level(OPEN, LANCEDB_LOG="warn") == "warn"


def test_tables_are_made_from_the_sites_columns_and_rows_are_replaced_by_key(tmp_path, shape):
    schema = shape[0]
    index = open_index(tmp_path, shape)
    assert not index.has_data() and index.stats() == {"passages": 0, "vectors": 0}
    assert index.search_words("budget", None, 5) == [] and index.search_meaning(vectors(1)[0], None, 5) == []
    rows = passages(schema, 30)
    index.replace(["k0", "k1", "k2"], rows)
    index.add_vectors(["k0", "k1", "k2"], rows, vectors(30))
    index.build_indexes()
    assert index.passages().schema.names == [n for n, _ in [*schema.filter_fields, *schema.passage_fields]]
    assert index.vectors().schema.names == [*schema.filter_names, "vector"]
    assert index.has_data() and index.stats() == {"passages": 30, "vectors": 30}
    assert index.names() == {"passages", "vectors"}

    found = index.search_words("number17", None, 5)
    assert [r["passage_id"] for r in found] == ["p17"] and found[0]["_score"] > 0
    assert [r["passage_id"] for r in index.search_words("number17", "source_key = 'k0'", 5)] == []
    assert {r["source_key"] for r in index.search_words("libraries", "source_key IN ('k1', 'k2')", 9)} == {"k1", "k2"}

    # reloading a key replaces its passages and drops their vectors, which are then made again
    changed = [{**passage(schema, 10), "text": "Now about allotments.", "search_text": "Heading 10\nNow about allotments."}]
    index.replace(["k1"], changed)
    assert index.stats() == {"passages": 21, "vectors": 20}
    assert index.embedded_ids(["k0", "k1", "k2"]) == {f"p{i}" for i in [*range(10), *range(20, 30)]}
    index.add_vectors(["k1"], changed, vectors(1, seed=5))
    index.add_vectors(["k1"], changed, vectors(1, seed=5))  # again: replaced, not added twice
    assert index.stats() == {"passages": 21, "vectors": 21}
    assert [r["passage_id"] for r in index.search_words("allotments", None, 5)] == ["p10"]

    by_id = index.passages_for(["p3", "p10", "nothing"])
    assert set(by_id) == {"p3", "p10"} and by_id["p10"]["text"] == "Now about allotments."
    assert index.passages_for([]) == {} and index.rows_for_keys([]) == []
    rows_k0 = index.rows_for_keys(["k0"])
    assert len(rows_k0) == 10 and set(rows_k0[0]) == {*schema.filter_names, "heading", "search_text"}


def test_search_by_meaning_filters_before_it_ranks_and_leaves_the_vectors_behind(tmp_path, shape):
    schema = shape[0]
    index = open_index(tmp_path, shape)
    rows, vecs = passages(schema, 40), vectors(40)
    index.replace([], rows)
    index.add_vectors([], rows, vecs)
    hits = index.search_meaning(vecs[7], None, 3)
    assert hits[0]["passage_id"] == "p7" and hits[0]["_distance"] < 1e-3
    assert set(hits[0]) == {*schema.filter_names, "_distance"}  # every column but the vector itself
    assert index.search_meaning(vecs[7], "source_key = 'k2'", 1)[0]["source_key"] == "k2"
    assert index.search_meaning(vecs[7], None, 3, exact=True)[0]["passage_id"] == "p7"
    assert index.search_meaning(vecs[7], None, 3, nprobes=4, refine_factor=5)[0]["passage_id"] == "p7"
    assert set(index.search_meaning(vecs[7], None, 1, columns=["passage_id"])[0]) == {"passage_id", "_distance"}
    assert index.search_meaning(list(map(float, vecs[7])), None, 1)[0]["passage_id"] == "p7"  # any row of floats


def test_new_tables_store_16_bit_vectors_and_find_the_same(tmp_path):
    index = open_index(tmp_path, MPS)
    vecs = vectors(50)
    index.add_vectors([], passages(MPS[0], 50), vecs)
    assert vector_type(index) == pa.float16() and index.meta.number_type == "float16"
    hits = index.search_meaning(vecs[7], None, 3)
    assert hits[0]["passage_id"] == "p7" and hits[0]["_distance"] < 1e-3
    back = index.vectors_for_keys(["k0"])
    assert back["p7"].dtype == np.float32 and np.allclose(back["p7"], vecs[7], atol=1e-3)


def test_an_old_32_bit_table_is_still_read_and_written(tmp_path):
    """Where MPs Stand's vectors were 32-bit before November 2026: such a table keeps its type until the site
    converts it, and is read and written in it meanwhile."""
    open_index(tmp_path, (MPS[0], MPS[1], "float32")).vectors()  # a 32-bit table, as made before
    os.remove(tmp_path / META_FILE)

    index = open_index(tmp_path, MPS)  # the site now asks for 16-bit
    vecs = vectors(40)
    rows = [{**r, "house": "commons" if i % 2 else "lords"} for i, r in enumerate(passages(MPS[0], 40))]
    index.add_vectors([], rows, vecs)
    assert vector_type(index) == pa.float32()  # written in the table's own type
    assert index.meta.number_type == "float32" and stored_meta(tmp_path).number_type == "float32"
    assert index.search_meaning(vecs[3], "house = 'commons'", 1)[0]["passage_id"] == "p3"
    assert np.array_equal(index.vectors_for_keys(["k0"])["p3"], vecs[3])


def test_only_the_changed_passages_of_a_key_need_embedding_again(tmp_path, shape):
    """One new meeting, or one corrected speech, must not re-embed the whole year: the vectors of a key can be read
    back, so a site keeps those of unchanged passages."""
    schema = shape[0]
    index = open_index(tmp_path, shape)
    rows, vecs = passages(schema, 4, per_key=4), vectors(4)
    index.replace(["k0"], rows)
    assert index.embedded_ids(["k0"]) == set() and index.vectors_for_keys(["k0"]) == {}
    index.add_vectors(["k0"], rows[:3], vecs[:3])
    assert index.embedded_ids(["k0"]) == {"p0", "p1", "p2"}  # an embedding job stopped part-way carries on
    before = index.vectors_for_keys(["k0"])
    kept = np.stack([before["p0"], vectors(1, seed=9)[0], before["p2"], vecs[3]])
    index.add_vectors(["k0"], rows, kept)
    after = index.vectors_for_keys(["k0"])
    assert len(after) == 4 and after["p0"].dtype == np.float32
    for pid in ("p0", "p2"):
        assert np.array_equal(before[pid], after[pid])
    assert not np.array_equal(before["p1"], after["p1"])
    assert index.vectors_for_keys([]) == {} and index.embedded_ids([]) == set()


def test_reading_writes_no_new_version_and_every_write_does(tmp_path, shape):
    """Each write leaves a new version of the index on disk, so an update with nothing new must write nothing."""
    schema = shape[0]
    index = open_index(tmp_path, shape)
    assert index.versions() == {}
    rows = passages(schema, 20)
    index.replace([], rows)
    index.add_vectors([], rows, vectors(20))
    index.refresh()
    versions = index.versions()
    assert set(versions) == {"passages", "vectors"}
    again = open_index(tmp_path, shape)
    again.search_words("budget", None, 5), again.search_meaning(vectors(1)[0], None, 5), again.stats()
    again.rows_for_keys(["k0"]), again.vectors_for_keys(["k0"]), again.unmerged(), again.has_word_index()
    assert again.versions() == versions
    again.replace(["k1"], rows[10:])
    assert again.versions()["passages"] > versions["passages"]


def test_an_update_merges_new_rows_and_cleans_up(tmp_path, shape, monkeypatch):
    schema = shape[0]
    index = open_index(tmp_path, shape)
    rows = passages(schema, 30)
    index.replace([], rows)
    index.add_vectors([], rows, vectors(30))
    assert not index.has_word_index()
    assert index.refresh() == "built" and index.has_word_index() and index.unmerged() == 0
    assert index.has_index("vectors", "passage_id") and not index.has_index("vectors", "vector")
    scalar = shape[1]
    indexed = {c for ix in index.passages().list_indices() for c in ix.columns}
    assert indexed == {"search_text", *scalar.btree, *scalar.bitmap, *scalar.label_list}

    more = passages(schema, 5, start=30)
    index.replace(["k3"], more)
    index.add_vectors(["k3"], more, vectors(5, seed=3))
    assert index.unmerged() == 5
    monkeypatch.setattr(index, "build_indexes", lambda vectors=True: pytest.fail("a routine update rebuilt the indexes"))
    tidied = []
    real = index.tidy
    monkeypatch.setattr(index, "tidy", lambda: (tidied.append(1), real()))
    assert index.refresh() == "merged" and tidied == [1]
    assert index.unmerged() == 0
    assert [r["record_id"] for r in index.search_words("number33", None, 10)].count("r33") == 1


def test_tidying_drops_superseded_versions_once_they_are_an_hour_old(tmp_path, monkeypatch):
    index = open_index(tmp_path, COUNCILS)
    index.replace([], passages(COUNCILS[0], 5))
    seen = []
    real = index.db.open_table

    def opened(name):
        table = real(name)
        monkeypatch.setattr(table, "optimize", lambda **kw: seen.append((name, kw)), raising=False)
        return table

    monkeypatch.setattr(index.db, "open_table", opened)
    index.tidy()
    assert seen == [("passages", {"cleanup_older_than": timedelta(hours=1)})]


def test_the_meaning_index_is_trained_again_only_when_vectors_grow_by_a_fifth(tmp_path):
    schema = COUNTRIES[0]
    index = open_index(tmp_path, COUNTRIES, min_vector_index_rows=256)
    index.replace([], passages(schema, 300, per_key=1000))
    assert index.refresh() == "built"   # no vectors yet: no meaning-search index
    assert index.trained_on() is None and not index.has_index("vectors", "vector")
    index.add_vectors([], passages(schema, 300, per_key=1000), vectors(300))
    assert index.refresh() == "built" and index.trained_on() == 300 and index.has_index("vectors", "vector")
    for upto, outcome, trained in ((330, "merged", 300), (370, "built", 370)):
        rows = passages(schema, upto, per_key=1000)
        index.replace(["k0"], rows)
        index.add_vectors(["k0"], rows, vectors(upto))
        assert index.refresh() == outcome
        assert index.trained_on() == trained
    assert json.loads((tmp_path / TRAINED_FILE).read_text()) == {"vectors": 370}  # Where Councils Stand's own file
    assert index.unmerged() == 0
    assert index.search_meaning(vectors(370)[11], None, 3, refine_factor=5)[0]["passage_id"] == "p11"


def test_too_few_vectors_get_no_meaning_index_and_a_rebuild_by_hand_records_its_size(tmp_path):
    index = open_index(tmp_path, MPS)
    assert index.build_vector_index() is None  # no vectors table at all
    rows = passages(MPS[0], 300, per_key=1000)
    index.replace([], rows)
    index.add_vectors([], rows, vectors(300))
    index.build_indexes()
    assert index.build_vector_index() is None and index.trained_on() is None  # under 10,000: every vector is compared
    assert not index.has_index("vectors", "vector") and index.has_index("vectors", "passage_id")
    assert not index.ensure_vector_ids()  # already there
    index.rebuild_vector_index(128)
    assert index.has_index("vectors", "vector") and index.trained_on() == 300
    assert {tuple(ix.columns) for ix in index.vectors().list_indices()} == {("vector",), ("passage_id",)}


def test_a_full_refresh_builds_everything_again(tmp_path):
    index = open_index(tmp_path, COUNCILS, min_vector_index_rows=256)
    rows = passages(COUNCILS[0], 260, per_key=1000)
    index.replace([], rows)
    index.add_vectors([], rows, vectors(260))
    assert index.refresh() == "built" and index.trained_on() == 260
    assert index.refresh() == "merged"
    index.note_trained(100)
    assert index.refresh(full=True) == "built" and index.trained_on() == 260


def test_indexes_for_columns_added_later_are_built_once(tmp_path):
    """Where MPs Stand's portfolio columns were indexed after the first build: an existing index gets them once."""
    schema, scalar, number = MPS
    first = LanceIndex(tmp_path, HashingEmbedder(DIM), schema=schema, scalar_columns=replace(scalar, label_list=()))
    assert not first.ensure_scalar_indexes(scalar.label_list)  # nothing indexed yet: nothing to add to
    first.replace([], passages(schema, 20))
    first.build_indexes()
    index = open_index(tmp_path, MPS)
    have = {c for ix in index.passages().list_indices() for c in ix.columns}
    assert not have & set(scalar.label_list)
    assert index.ensure_scalar_indexes(scalar.label_list) is True
    have = {c for ix in index.passages().list_indices() for c in ix.columns}
    assert set(scalar.label_list) <= have
    assert index.ensure_scalar_indexes(scalar.label_list) is False


def test_a_scalar_index_that_cannot_be_built_is_skipped_with_a_warning(tmp_path, caplog):
    schema, scalar, _ = COUNCILS
    index = LanceIndex(tmp_path, HashingEmbedder(DIM), schema=schema,
                       scalar_columns=replace(scalar, btree=(*scalar.btree, "no_such_column")))
    index.replace([], passages(schema, 5))
    index.build_indexes()
    assert "scalar index on no_such_column skipped" in caplog.text and index.has_word_index()


def test_specific_copies_of_records_are_deleted_with_their_vectors(tmp_path, shape):
    schema = shape[0]
    index = open_index(tmp_path, shape)
    rows = passages(schema, 6, per_key=3) + [{**passage(schema, 2, per_key=3), "passage_id": "p2-copy",
                                              "source_key": "k1"}]
    index.replace([], rows)
    index.add_vectors([], rows, vectors(7))
    assert index.delete_copies([("r2", "k1"), ("r4", "k1"), ("r5", "k0")]) == 3  # the last pair matches nothing
    left = sorted(r["passage_id"] for r in index.rows_for_keys(["k0", "k1"]))
    assert left == ["p0", "p1", "p2", "p3", "p5"]
    assert index.embedded_ids(["k0", "k1"]) == set(left)
    assert index.delete_copies([]) == 0


def test_another_name_for_the_vectors_table_leaves_the_usual_one_alone(tmp_path):
    """Where MPs Stand builds a replacement table under another name before swapping it in."""
    index = open_index(tmp_path, MPS)
    rows = passages(MPS[0], 10)
    index.add_vectors([], rows, vectors(10))
    other = open_index(tmp_path, MPS, vectors="vectors_f16")
    assert other.stats() == {"passages": 0, "vectors": 0}
    other.add_vectors([], rows[:4], vectors(4))
    assert other.stats()["vectors"] == 4 and index.stats()["vectors"] == 10
    assert other.names() == {"vectors", "vectors_f16"} and other.versions().keys() == {"vectors_f16"}


# --------------------------------------------------------------------------- new: what the index was built with


def test_the_index_records_what_it_was_built_with_beside_it(tmp_path, shape):
    index = open_index(tmp_path, shape)
    stored = json.loads((tmp_path / META_FILE).read_text())
    assert stored == {"embedder_id": "hashing-16", "dimension": 16, "number_type": shape[2], "schema_version": 1}
    assert index.meta == stored_meta(tmp_path) == IndexMeta("hashing-16", 16, shape[2], 1)
    assert stored_meta(tmp_path / "nowhere") is None
    again = open_index(tmp_path, shape, IndexMeta("hashing-16", 16, shape[2], 1))  # the meta itself will do
    assert again.meta == index.meta


def filled(path, shape, n: int = 20) -> LanceIndex:
    index = open_index(path, shape)
    rows = passages(shape[0], n)
    index.replace([], rows)
    index.add_vectors([], rows, vectors(n))
    index.build_indexes()
    return index


class Other:
    """An embedder as far as an index is concerned: an id and a dimension."""

    def __init__(self, id: str, dimension: int):
        self.id, self.dimension = id, dimension


@pytest.mark.parametrize("other, what", [(Other("another-model", DIM), "embedder_id"),
                                          (Other("hashing-16", DIM * 2), "dimension")])
def test_an_index_built_with_another_embedder_is_refused_on_opening(tmp_path, shape, other, what):
    filled(tmp_path, shape)
    with pytest.raises(IndexOutOfDate, match="rebuild it") as refused:
        open_index(tmp_path, shape, other)
    stored, wanted = refused.value.stored, refused.value.wanted
    assert getattr(stored, what) != getattr(wanted, what)
    assert stored == IndexMeta("hashing-16", DIM, shape[2], 1)
    assert stored_meta(tmp_path) == stored  # and the refusal changed nothing
    assert open_index(tmp_path, shape).stats() == {"passages": 20, "vectors": 20}


def test_an_index_built_with_another_schema_is_refused_on_opening(tmp_path):
    filled(tmp_path, COUNCILS)
    changed = (replace(COUNCILS[0], version=2), COUNCILS[1], "float32")
    with pytest.raises(IndexOutOfDate) as refused:
        open_index(tmp_path, changed)
    assert (refused.value.stored.schema_version, refused.value.wanted.schema_version) == (1, 2)


def test_search_by_words_carries_on_while_the_vectors_await_a_rebuild(tmp_path, shape):
    """What a site does when the embedding model has changed: it opens the index as it stands, searches by words,
    and says so in its update report until everything is embedded again."""
    filled(tmp_path, shape)
    new_model = Other("another-model", 8)
    with pytest.raises(IndexOutOfDate):
        open_index(tmp_path, shape, new_model)
    as_it_stands = open_index(tmp_path, shape, None)
    assert as_it_stands.meta == IndexMeta("hashing-16", DIM, shape[2], 1)
    assert [r["passage_id"] for r in as_it_stands.search_words("number7", None, 3)] == ["p7"]
    assert as_it_stands.stats() == {"passages": 20, "vectors": 20} and as_it_stands.unmerged() == 0
    with pytest.raises(RuntimeError, match="adds no vectors"):
        as_it_stands.add_vectors(["k0"], passages(shape[0], 1), vectors(1, dim=8))
    assert as_it_stands.stats()["vectors"] == 20

    # the rebuild: the old vectors go, the new embedder is recorded, and its vectors are the only ones there are
    as_it_stands.start_again(new_model, number_type=shape[2])
    assert as_it_stands.meta == stored_meta(tmp_path) == IndexMeta("another-model", 8, shape[2], 1)
    assert as_it_stands.stats() == {"passages": 20, "vectors": 0} and as_it_stands.trained_on() is None
    rebuilt = open_index(tmp_path, shape, new_model)
    rebuilt.add_vectors(["k0"], passages(shape[0], 10), vectors(10, dim=8))
    assert rebuilt.stats()["vectors"] == 10
    assert rebuilt.search_meaning(vectors(10, dim=8)[4], None, 1)[0]["passage_id"] == "p4"
    with pytest.raises(IndexOutOfDate):
        open_index(tmp_path, shape)  # the old model is now the one refused


def test_a_writer_is_refused_once_the_index_has_been_started_again_by_another(tmp_path, shape):
    """Two processes have the index open; one starts it again with a new model. The other, still holding the old
    model, must add nothing: vectors from two models are never mixed, even when they are the same length."""
    stale = filled(tmp_path, shape)
    new_model = Other("another-model", DIM)
    open_index(tmp_path, shape, None).start_again(new_model, number_type=shape[2])
    fresh = open_index(tmp_path, shape, new_model)
    fresh.add_vectors(["k0"], passages(shape[0], 3), vectors(3, seed=1))
    row = passages(shape[0], 1, start=50)
    for write in (lambda: stale.add_vectors(["k5"], row, vectors(1)), lambda: stale.replace(["k5"], row),
                  lambda: stale.delete_copies([("r0", "k0")]), stale.build_indexes, stale.rebuild_vector_index):
        with pytest.raises(IndexOutOfDate) as refused:
            write()
        assert refused.value.stored.embedder_id == "another-model"
        assert refused.value.wanted.embedder_id == "hashing-16"
    assert fresh.stats() == {"passages": 20, "vectors": 3}


def test_vectors_of_the_wrong_length_are_refused_and_nothing_is_written(tmp_path, shape):
    index = filled(tmp_path, shape)
    before = index.versions()
    with pytest.raises(IndexOutOfDate):
        index.add_vectors(["k0"], passages(shape[0], 2), vectors(2, dim=DIM * 2))
    with pytest.raises(ValueError, match="2 rows and 3 vectors"):
        index.add_vectors(["k0"], passages(shape[0], 2), vectors(3))
    assert index.versions() == before and index.stats()["vectors"] == 20


def test_an_index_made_before_the_meta_was_kept_adopts_it_when_its_vectors_fit(tmp_path, shape):
    """Every site's index today: tables, and no record of what made them."""
    filled(tmp_path, shape)
    os.remove(tmp_path / META_FILE)
    with pytest.raises(IndexOutOfDate) as refused:
        open_index(tmp_path, shape, Other("fastembed-model", 384))
    assert refused.value.stored == IndexMeta("unknown", DIM, shape[2], 1)
    assert not (tmp_path / META_FILE).exists()  # nothing was adopted
    index = open_index(tmp_path, shape, Other("fastembed-model", DIM))
    assert index.meta == stored_meta(tmp_path) == IndexMeta("fastembed-model", DIM, shape[2], 1)
    assert index.stats() == {"passages": 20, "vectors": 20}
    with pytest.raises(IndexOutOfDate):
        open_index(tmp_path, shape)  # from now on it is that model's


def test_an_index_with_no_meta_opened_as_it_stands_says_what_its_table_shows(tmp_path, shape):
    filled(tmp_path, shape)
    os.remove(tmp_path / META_FILE)
    index = open_index(tmp_path, shape, None)
    assert index.meta == IndexMeta("unknown", DIM, shape[2], 1)
    assert not (tmp_path / META_FILE).exists()  # looking is not adopting
    assert open_index(tmp_path / "empty", shape, None).meta == IndexMeta("unknown", 0, "float32", 1)
    assert open_index(tmp_path / "empty", shape, None).stats() == {"passages": 0, "vectors": 0}


def test_with_no_vectors_yet_any_embedder_may_be_the_first(tmp_path, shape):
    """Passages are loaded before anything is embedded: until there are vectors there is nothing to mix."""
    index = open_index(tmp_path, shape)
    index.replace([], passages(shape[0], 10))
    index.build_indexes()
    other = open_index(tmp_path, shape, Other("fastembed-model", 384))
    assert other.meta == stored_meta(tmp_path) == IndexMeta("fastembed-model", 384, shape[2], 1)
    # the first opener is now the stale one, and its vectors are refused although no table exists yet
    with pytest.raises(IndexOutOfDate):
        index.add_vectors(["k0"], passages(shape[0], 10), vectors(10))
    assert "vectors" not in index.names()
    index.replace(["k0"], passages(shape[0], 10))  # passages are not the embedder's: still welcome


def test_an_index_with_nothing_in_it_yet_binds_nobody(tmp_path):
    open_index(tmp_path, COUNCILS)  # opened once, nothing loaded
    changed = (replace(COUNCILS[0], version=2), COUNCILS[1], "float16")
    index = open_index(tmp_path, changed, Other("fastembed-model", 384))
    assert index.meta == stored_meta(tmp_path) == IndexMeta("fastembed-model", 384, "float16", 2)


def test_the_number_type_is_recorded_and_never_refused(tmp_path):
    """A table is always read and written in its own number type, so asking for the other is not a mismatch."""
    filled(tmp_path, COUNTRIES)  # 32-bit
    index = open_index(tmp_path, (COUNTRIES[0], COUNTRIES[1], "float16"))
    assert index.meta.number_type == "float32" and vector_type(index) == pa.float32()
    assert stored_meta(tmp_path).number_type == "float32"
    with pytest.raises(ValueError, match="float16 or float32"):
        open_index(tmp_path / "x", (COUNTRIES[0], COUNTRIES[1], "float64"))


def test_a_meta_file_that_cannot_be_read_is_treated_as_none(tmp_path, shape):
    filled(tmp_path, shape)
    (tmp_path / META_FILE).write_text("{not json")
    assert stored_meta(tmp_path) is None
    assert open_index(tmp_path, shape).meta == IndexMeta("hashing-16", DIM, shape[2], 1)  # adopted again: it fits
    assert stored_meta(tmp_path) is not None


def test_starting_again_with_the_passages_too_empties_the_index(tmp_path):
    index = filled(tmp_path, COUNCILS)
    changed = replace(COUNCILS[0], version=2)
    again = LanceIndex(tmp_path, None, schema=changed, scalar_columns=COUNCILS[1])
    again.start_again(RecordingEmbedder(DIM), passages=True)
    assert again.names() == set() and again.meta == IndexMeta("recording-16", DIM, "float32", 2)
    with pytest.raises(IndexOutOfDate):
        index.replace([], passages(COUNCILS[0], 1))


# --------------------------------------------------------------------------- the same as each site's own copy


def site_index(name: str):
    spec = importlib.util.spec_from_file_location(f"{SITES[name][1]}_index_lance", site_file(name, "index/lance.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def comparable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(({k: (round(v, 5) if isinstance(v, float) else v) for k, v in r.items()} for r in rows),
                  key=lambda r: r["passage_id"])


@pytest.mark.parametrize("name", list(SITES))
def test_the_columns_here_are_the_sites_own(name):
    theirs = site_index(name)
    schema, scalar, _ = SHAPES[name]
    assert list(schema.filter_fields) == theirs.FILTER_FIELDS
    assert pa.schema([*schema.filter_fields, *schema.passage_fields]) == theirs.PASSAGE_SCHEMA
    assert theirs._QUERY_JUNK.pattern == __import__("wts_core.adapters.lancedb").adapters.lancedb._QUERY_JUNK.pattern
    assert timedelta(hours=1) == theirs.KEEP_OLD_VERSIONS == KEEP_OLD_VERSIONS


@pytest.mark.parametrize("name", list(SITES))
def test_the_same_writes_and_searches_give_what_the_sites_copy_gives(tmp_path, name):
    """Each site's ``SearchIndex`` and the base are given the same rows, vectors and questions."""
    module = site_index(name)
    schema, scalar, number = SHAPES[name]
    theirs = module.SearchIndex(tmp_path / "theirs", DIM)
    ours = LanceIndex(tmp_path / "ours", HashingEmbedder(DIM), schema=schema, scalar_columns=scalar,
                      number_type=number)
    rows, vecs = passages(schema, 60), vectors(60)
    theirs.replace_keys([], rows), ours.replace([], rows)
    theirs.add_vectors([], rows, vecs), ours.add_vectors([], rows, vecs)
    theirs.build_indices(), ours.build_indexes()
    changed = [{**r, "text": "Rewritten.", "search_text": f"{r['heading']}\nRewritten about allotments."}
               for r in rows[10:14]]
    theirs.replace_keys(["k1"], changed), ours.replace(["k1"], changed)
    theirs.add_vectors(["k1"], changed, vecs[:4]), ours.add_vectors(["k1"], changed, vecs[:4])
    assert theirs.delete_copies([("r3", "k0")]) == ours.delete_copies([("r3", "k0")])
    theirs.optimize(), ours.tidy()

    assert ours.passages().schema == theirs.passages().schema
    assert ours.vectors().schema == theirs.vectors().schema
    assert ours.stats() == theirs.stats() and ours.has_data() == theirs.has_data()
    for table in ("passages", "vectors"):
        mine = {(tuple(ix.columns), ix.index_type) for ix in ours.db.open_table(table).list_indices()}
        assert mine == {(tuple(ix.columns), ix.index_type) for ix in theirs.db.open_table(table).list_indices()}
    for query, where in (("budget", None), ("allotments", None), ("number27 OR (bins)", "source_key = 'k2'"),
                         ("libraries", f"date >= {date_lit(date(2025, 1, 1))} AND year = 2026"), ("!!", None)):
        assert comparable(ours.search_words(query, where, 20)) == comparable(theirs.bm25(query, where, 20))
    for q, where in ((vecs[7], None), (vecs[20], "source_key IN ('k2', 'k3')"), (vecs[1], "record_id = 'r1'")):
        assert comparable(ours.search_meaning(q, where, 5)) == comparable(theirs.vector(q, where, 5))
        assert comparable(ours.search_meaning(q, where, 5, exact=True, columns=["passage_id"])) == \
            comparable(theirs.vector(q, where, 5, exact=True, columns=["passage_id"]))
    assert comparable(ours.rows_for_keys(["k0", "k1"])) == comparable(theirs.rows_for_keys(["k0", "k1"]))
    assert ours.passages_for(["p1", "p11", "p59"]) == theirs.passages_for(["p1", "p11", "p59"])
    assert ours.ensure_vector_ids() == theirs.ensure_vector_ids()
    if hasattr(theirs, "vectors_for_keys"):
        mine, site = ours.vectors_for_keys(["k1", "k5"]), theirs.vectors_for_keys(["k1", "k5"])
        assert mine.keys() == site.keys() and all(np.array_equal(mine[k], site[k]) for k in mine)
    if hasattr(theirs, "embedded_ids"):
        assert ours.embedded_ids(["k0", "k1"]) == theirs.embedded_ids(["k0", "k1"])
        assert ours.unmerged() == theirs.unmerged()  # Where Countries Stand's count, of both indexes


@pytest.mark.parametrize("name", list(SITES))
def test_an_index_a_site_made_itself_opens_and_is_used_as_it_is(tmp_path, name):
    """Today's indexes: made by the site's own code, with no record of the embedder. They must open."""
    module = site_index(name)
    schema, scalar, number = SHAPES[name]
    theirs = module.SearchIndex(tmp_path, DIM)
    rows, vecs = passages(schema, 30), vectors(30)
    theirs.replace_keys([], rows)
    theirs.add_vectors([], rows, vecs)
    theirs.build_indices()

    with pytest.raises(IndexOutOfDate):  # a model of another dimension did not make this
        LanceIndex(tmp_path, Other("fastembed-model", 384), schema=schema, scalar_columns=scalar, number_type=number)
    ours = LanceIndex(tmp_path, HashingEmbedder(DIM), schema=schema, scalar_columns=scalar, number_type=number)
    assert ours.meta == IndexMeta("hashing-16", DIM, number, 1)
    assert ours.stats() == {"passages": 30, "vectors": 30} and ours.unmerged() == 0
    assert comparable(ours.search_words("budget", None, 9)) == comparable(theirs.bm25("budget", None, 9))
    assert comparable(ours.search_meaning(vecs[4], None, 5)) == comparable(theirs.vector(vecs[4], None, 5))
    more = passages(schema, 5, start=30)
    ours.replace(["k3"], more)
    ours.add_vectors(["k3"], more, vectors(5, seed=2))
    assert ours.refresh() == "merged"
    assert theirs.stats() == {"passages": 35, "vectors": 35}  # and the site's own code still reads it
    assert [r["passage_id"] for r in theirs.bm25("number33", None, 3)] == ["p33"]
