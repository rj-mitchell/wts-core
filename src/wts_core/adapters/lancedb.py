"""The search index behind ``ports.VectorIndex``: LanceDB tables for search by words (BM25) and by meaning.

Two tables share the same filter columns:

* the passages table  every searchable passage, with a full-text index on ``search_text``. Built straight after
  loading, so search by words is available at once.
* the vectors table   one embedding for each passage. Filled by the (slower, resumable) embedding job; search by
  meaning uses whatever is embedded so far.

Rows are keyed by ``source_key`` (a file, or a source and year), so reloading a key replaces its rows.

``LanceIndex`` is the twenty or so methods the three sites' ``index/lance.py`` shared, written once. A site
subclasses nothing: it passes its columns (``IndexSchema``), the columns to index for filtering
(``ScalarColumns``) and, if they are not the usual ones, its table names; what is its own (Where MPs Stand's
``similarities``, Where Countries Stand's ``set_groups``) it writes as functions over ``index.passages()``,
``index.vectors()`` and ``index.db``. Where the copies differed by accident the best is taken:

* the number type of stored vectors is read from the table, and a failed search is tried once more (Where MPs
  Stand: a table made with 32-bit vectors keeps them, and is read and written as it is, until the site converts it);
* ``unmerged`` counts the rows waiting for the meaning-search index as well as the word index, vectors come back
  straight from Arrow, and ``embedded_ids`` and ``versions`` exist (Where Countries Stand);
* when the meaning-search index is trained again is one rule (``vector_index_due``, Where Countries Stand's), with
  the count it was trained on kept in the index folder under the name Where Councils Stand uses
  (``vector_index.json``), so that site's count carries over; ``build_vector_index`` and ``rebuild_vector_index``
  both record it.

New: what the index was built with (``ports.IndexMeta``: the embedder's id, the dimension, the number type and the
schema's version) is kept beside it in ``wts_index.json`` and compared when the index is opened and before every
write. A difference in the embedder, the dimension or the schema raises ``ports.IndexOutOfDate``: vectors from two
models are never mixed. The number type is recorded but never refused, since a table is always written in its own.
An index made before the file existed adopts the meta it is opened with, provided its vectors have that dimension.

``lancedb``, ``pyarrow`` and ``numpy`` are imported when first used.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from wts_core.ports import Embedder, IndexMeta, IndexOutOfDate

__all__ = [
    "KEEP_OLD_VERSIONS",
    "META_FILE",
    "TRAINED_FILE",
    "IndexSchema",
    "LanceIndex",
    "ScalarColumns",
    "date_lit",
    "retry_once",
    "sanitise_query",
    "sql_list",
    "sql_str",
    "stored_meta",
    "vector_index_due",
]

log = logging.getLogger(__name__)

META_FILE = "wts_index.json"  # in the index folder: what the index was built with
TRAINED_FILE = "vector_index.json"  # in the index folder: how many vectors the meaning-search index was trained on
UNKNOWN_EMBEDDER = "unknown"  # the embedder of an index nobody recorded

# the columns every site's tables have, by these names
KEY, PASSAGE_ID, RECORD_ID, TEXT, VECTOR = "source_key", "passage_id", "record_id", "search_text", "vector"

# LanceDB never overwrites: every delete, add and index build writes a new version of the table and leaves the old
# files on disk. Every read opens the latest version, so older versions only take disk space. Lance would keep them
# for a week: about 10 GB after one large re-enrichment or clean-up (Where MPs Stand, where this was learnt).
# ``tidy`` drops them once they are an hour old, so it runs after every update that writes to the index.
KEEP_OLD_VERSIONS = timedelta(hours=1)


def _lancedb() -> Any:
    # LanceDB's own warnings (while the vector index is small, one per cluster it trains) would fill the update
    # logs: only its errors are shown. Read once, when LanceDB is first imported, so it is set here, before that.
    # LANCEDB_LOG=warn (or info) in the environment brings them back.
    os.environ.setdefault("LANCEDB_LOG", "error")
    import lancedb

    return lancedb


@dataclass(frozen=True)
class IndexSchema:
    """A site's columns. ``filter_fields`` are in both tables (they are what a search filters on, and must include
    ``passage_id``, ``record_id`` and ``source_key``); ``passage_fields`` are the further columns of the passages
    table (and must include ``search_text``). Each is a list of name and pyarrow type, as the sites wrote them.
    ``version`` changes when the columns do: an index built with another is out of date."""

    filter_fields: Sequence[tuple[str, Any]]
    passage_fields: Sequence[tuple[str, Any]]
    version: int = 1
    # what ``rows_for_keys`` returns beside the filter columns: what a site needs to embed a passage
    row_columns: tuple[str, ...] = ("heading", "search_text")

    @property
    def filter_names(self) -> list[str]:
        return [name for name, _ in self.filter_fields]


@dataclass(frozen=True)
class ScalarColumns:
    """The columns of the passages table to index so that filtered searches skip the rows that do not match:
    ``btree`` for columns of many values (ids, dates), ``bitmap`` for those of few, ``label_list`` for lists."""

    btree: tuple[str, ...]
    bitmap: tuple[str, ...]
    label_list: tuple[str, ...] = ()


_QUERY_JUNK = re.compile(r"[\"'()\[\]{}:^~*+\-!?\\/<>=|&]")


def sanitise_query(text: str) -> str:
    """Plain words only: user text must never be read as full-text query syntax."""
    return " ".join(_QUERY_JUNK.sub(" ", text or "").split())


def sql_str(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def sql_list(values: Iterable[str]) -> str:
    return "[" + ", ".join(sql_str(v) for v in values) + "]"


def date_lit(d: date) -> str:
    return f"DATE '{d.isoformat()}'"


def _in(column: str, values: Iterable[str]) -> str:
    return f"{column} IN ({', '.join(sql_str(v) for v in values)})"


def retry_once[T](fn: Callable[[], T]) -> T:
    """Run a read, and once more if it fails: a site's conversion of a table swaps its folder for a new one, and a
    search that had opened the old one just before reads files that are no longer there. Opened again, it reads the
    new one."""
    try:
        return fn()
    except Exception as exc:
        log.info("search failed (%s); trying once more", exc)
        return fn()


def vector_index_due(vectors: int, trained_on: int | None, has_index: bool, *, minimum: int = 10_000,
                     growth: float = 1.2) -> bool:
    """Whether the meaning-search index should be (re)trained, rather than have new vectors merged into it.

    It is built once there are ``minimum`` vectors (below that, every vector is compared, which is quick enough),
    and trained again once there are ``growth`` times as many as it was trained on: vectors added later join its
    existing partitions, which grow, and searches slow down. An index whose count was never recorded is trained
    again once.
    """
    if vectors < minimum:
        return False
    return not has_index or not trained_on or vectors > growth * trained_on


def stored_meta(path: Path) -> IndexMeta | None:
    """What the index in this folder says it was built with, or None when it does not say."""
    try:
        raw = json.loads((Path(path) / META_FILE).read_text())
        return IndexMeta(embedder_id=str(raw["embedder_id"]), dimension=int(raw["dimension"]),
                         number_type=str(raw.get("number_type", "float32")),
                         schema_version=int(raw.get("schema_version", 1)))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _differs(stored: IndexMeta, wanted: IndexMeta, vectors: bool = True) -> bool:
    """Whether an index built with ``stored`` cannot serve ``wanted``. Without a vectors table there is nothing of
    the embedder's to mix, and only the schema counts. The number type never counts: each table is read and written
    in its own."""
    if stored.schema_version != wanted.schema_version:
        return True
    return vectors and (stored.embedder_id, stored.dimension) != (wanted.embedder_id, wanted.dimension)


def _number_type(name: str) -> Any:
    import pyarrow as pa

    types = {"float16": pa.float16(), "float32": pa.float32()}
    if name not in types:
        raise ValueError(f"vectors are stored as float16 or float32, not {name!r}")
    return types[name]


def _number_name(value_type: Any) -> str:
    import pyarrow as pa

    return "float16" if value_type == pa.float16() else "float32"


def _vector_array(vectors: Any, value_type: Any) -> Any:
    """Embeddings (rows of 32-bit floats) as a vector column of the given number type."""
    import numpy as np
    import pyarrow as pa

    vectors = np.asarray(vectors)
    flat = pa.array(vectors.astype(value_type.to_pandas_dtype()).reshape(-1), type=value_type)
    return pa.FixedSizeListArray.from_arrays(flat, vectors.shape[1])


class LanceIndex:
    """A site's search index in one folder (``ports.VectorIndex``, and the further methods the sites' loading,
    embedding and update code call).

    ``embedder`` is the embedder the site will use (anything with ``id`` and ``dimension``), or an ``IndexMeta``.
    The index must have been built with the same, or ``IndexOutOfDate`` is raised here: catch it, carry on with
    search by words through ``LanceIndex(path, None, …)``, and say so in the update report until the vectors are
    made again (``start_again``). ``None`` opens the index as it stands, whatever it was built with: for search by
    words, counts and the status command. Such an index adds no vectors.

    ``number_type`` ("float32" or "float16") is the type a new vectors table gets; an existing table keeps its own.
    """

    def __init__(self, path: Path, embedder: Embedder | IndexMeta | None, *, schema: IndexSchema,
                 scalar_columns: ScalarColumns, passages: str = "passages", vectors: str = "vectors",
                 number_type: str = "float32", min_vector_index_rows: int = 10_000,
                 vector_index_growth: float = 1.2) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.schema = schema
        self.scalar_columns = scalar_columns
        self.passages_name = passages
        self.vectors_name = vectors  # another name only while a site builds a replacement table
        self.min_vector_index_rows = min_vector_index_rows
        self.vector_index_growth = vector_index_growth
        self.db = _lancedb().connect(str(self.path))
        self._wanted = self._meta_for(embedder, number_type)
        self.meta = self._open(self._wanted)

    # ---- what the index was built with --------------------------------------------------------------------------

    def _meta_for(self, embedder: Embedder | IndexMeta | None, number_type: str) -> IndexMeta | None:
        if embedder is None or isinstance(embedder, IndexMeta):
            return embedder
        _number_type(number_type)
        return IndexMeta(embedder_id=embedder.id, dimension=int(embedder.dimension), number_type=number_type,
                         schema_version=self.schema.version)

    def _table_facts(self) -> tuple[int, str] | None:
        """The dimension and number type of the vectors there are, or None when there is no vectors table."""
        if self.vectors_name not in self.names():
            return None
        field = self.db.open_table(self.vectors_name).schema.field(VECTOR)
        return int(field.type.list_size), _number_name(field.type.value_type)

    def _open(self, wanted: IndexMeta | None) -> IndexMeta:
        stored = stored_meta(self.path)
        facts = self._table_facts()
        if wanted is None:  # as it stands
            if stored is not None:
                return replace(stored, number_type=facts[1]) if facts else stored
            return IndexMeta(UNKNOWN_EMBEDDER, facts[0] if facts else 0, facts[1] if facts else "float32",
                             self.schema.version)
        if stored is None:
            # an index made before the meta was kept (every site's, today): it is taken to have been built with
            # what it is opened with, unless its vectors plainly were not
            if facts and facts[0] != wanted.dimension:
                raise IndexOutOfDate(IndexMeta(UNKNOWN_EMBEDDER, facts[0], facts[1], wanted.schema_version), wanted)
            return self._store(replace(wanted, number_type=facts[1]) if facts else wanted)
        if facts and facts[0] != stored.dimension:  # the file and the table disagree: believe the table
            stored = replace(stored, dimension=facts[0])
        if _differs(stored, wanted, vectors=facts is not None):
            raise IndexOutOfDate(stored, wanted)
        settled = replace(wanted, number_type=facts[1]) if facts else wanted
        return self._store(settled) if settled != stored else settled

    def _store(self, meta: IndexMeta) -> IndexMeta:
        tmp = self.path / (META_FILE + ".tmp")
        tmp.write_text(json.dumps(asdict(meta), indent=1, sort_keys=True) + "\n")
        tmp.replace(self.path / META_FILE)
        return meta

    def _check(self, vectors: bool | None = None) -> None:
        """Before every write: the index must still be what this writer opened. Another process may have started
        it again with another embedder since. ``vectors`` says whether the embedder matters to this write: always
        when vectors are added, otherwise only if there are vectors."""
        if self._wanted is None:
            return
        stored = stored_meta(self.path)
        if stored is None:
            self._store(self.meta)
        elif _differs(stored, self.meta, vectors=self.vectors_name in self.names() if vectors is None else vectors):
            raise IndexOutOfDate(stored, self.meta)

    def start_again(self, embedder: Embedder | IndexMeta, *, passages: bool = False,
                    number_type: str = "float32") -> None:
        """Throw the vectors away and record a new embedder: the first step of embedding everything again after the
        model changed. ``passages`` throws the passages away too, for a change of schema. Search by meaning finds
        nothing until vectors are added."""
        meta = self._meta_for(embedder, number_type)
        assert meta is not None
        for name in (self.vectors_name, *((self.passages_name,) if passages else ())):
            if name in self.names():
                self.db.drop_table(name)
        (self.path / TRAINED_FILE).unlink(missing_ok=True)
        self._wanted = meta
        self.meta = self._store(meta)

    # ---- tables -------------------------------------------------------------------------------------------------

    def names(self) -> set[str]:
        res = self.db.list_tables()
        return set(getattr(res, "tables", res))

    def _passage_schema(self) -> Any:
        import pyarrow as pa

        return pa.schema([*self.schema.filter_fields, *self.schema.passage_fields])

    def _vector_schema(self, value_type: Any) -> Any:
        import pyarrow as pa

        return pa.schema([*self.schema.filter_fields, (VECTOR, pa.list_(value_type, self.meta.dimension))])

    def passages(self) -> Any:
        if self.passages_name not in self.names():
            return self.db.create_table(self.passages_name, schema=self._passage_schema())
        return self.db.open_table(self.passages_name)

    def vectors(self) -> Any:
        if self.vectors_name not in self.names():
            if self._wanted is None:
                raise RuntimeError(f"{self.path}: opened as it stands (no embedder), so no vectors table is made")
            return self.db.create_table(self.vectors_name,
                                        schema=self._vector_schema(_number_type(self._wanted.number_type)))
        return self.db.open_table(self.vectors_name)

    def has_data(self) -> bool:
        return self.passages_name in self.names() and self.passages().count_rows() > 0

    # ---- writes -------------------------------------------------------------------------------------------------

    def replace(self, keys: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
        """Replace all passages (and their vectors) for the given source keys."""
        import pyarrow as pa

        self._check()
        tbl = self.passages()
        if keys:
            where = _in(KEY, keys)
            tbl.delete(where)
            if self.vectors_name in self.names():
                self.vectors().delete(where)
        if rows:
            tbl.add(pa.Table.from_pylist(list(rows), schema=self._passage_schema()))

    def delete_copies(self, pairs: Sequence[tuple[str, str]], chunk: int = 500) -> int:
        """Delete the passages and vectors of specific (record_id, source_key) copies of records."""
        self._check()
        names = self.names()
        for i in range(0, len(pairs), chunk):
            part = pairs[i:i + chunk]
            # the record_id clause can use the scalar index; the concat clause makes the match exact
            exact = _in(f"concat({RECORD_ID}, '|', {KEY})", (f"{r}|{k}" for r, k in part))
            where = f"{_in(RECORD_ID, sorted({r for r, _ in part}))} AND {exact}"
            for name in (self.passages_name, self.vectors_name):
                if name in names:
                    self.db.open_table(name).delete(where)
        return len(pairs)

    def add_vectors(self, keys: Sequence[str], rows: Sequence[Mapping[str, Any]], vectors: Any) -> None:
        """Replace the vectors of the given source keys with these: one row of ``vectors`` for each of ``rows``,
        which carry the filter columns."""
        import numpy as np
        import pyarrow as pa

        if self._wanted is None:
            raise RuntimeError(f"{self.path}: opened as it stands (no embedder), so it adds no vectors")
        self._check(vectors=True)
        if rows:
            vectors = np.asarray(vectors)
            if vectors.ndim != 2 or vectors.shape[1] != self.meta.dimension or len(vectors) != len(rows):
                width = int(vectors.shape[1]) if vectors.ndim == 2 else 0
                if width != self.meta.dimension:  # another model's vectors: never mixed in
                    raise IndexOutOfDate(self.meta, replace(self.meta, dimension=width))
                raise ValueError(f"{len(rows)} rows and {len(vectors)} vectors")
        tbl = self.vectors()
        if keys:
            tbl.delete(_in(KEY, keys))
        if not rows:
            return
        # in the table's own number type: 16-bit, or 32-bit in a table not yet converted
        value_type = tbl.schema.field(VECTOR).type.value_type
        cols: dict[str, Any] = {name: [r[name] for r in rows] for name in self.schema.filter_names}
        cols[VECTOR] = _vector_array(vectors, value_type)
        tbl.add(pa.Table.from_pydict(cols, schema=self._vector_schema(value_type)))

    # ---- indexes ------------------------------------------------------------------------------------------------

    def build_indexes(self, vectors: bool = True) -> None:
        """Build every index from scratch: for a first build, or after rewriting much of the index. Routine updates
        merge new rows into the existing indexes instead (``tidy``, or ``refresh`` which chooses)."""
        from lancedb.index import FTS

        self._check()
        tbl = self.passages()
        if tbl.count_rows() == 0:
            return
        tbl.create_index(TEXT, config=FTS(with_position=False, stem=True, remove_stop_words=True), replace=True)
        self.build_scalar_indexes(tbl)
        self.ensure_vector_ids()
        if vectors:
            self.build_vector_index()

    def build_vector_index(self) -> int | None:
        """Train the meaning-search index on the vectors there are now; returns how many, or None if too few."""
        if self.vectors_name not in self.names():
            return None
        vt = self.vectors()
        n = int(vt.count_rows())
        if n < self.min_vector_index_rows:
            return None
        from lancedb.index import IvfPq

        self._check()
        vt.create_index(VECTOR, config=IvfPq(distance_type="cosine",
                                             num_sub_vectors=max(1, self.meta.dimension // 8)), replace=True)
        self.note_trained(n)
        return n

    def rebuild_vector_index(self, rows_per_partition: int = 8192) -> None:
        """Rebuild the meaning-search index with partitions sized for the vectors there are now.

        The index is first built when there are few vectors, and later additions join its existing partitions; with
        millions of vectors in a few dozen partitions, each search reads a third of them. Searches carry on with the
        old index while the new one is built."""
        from lancedb.index import IvfPq

        self._check()
        vt = self.vectors()
        vt.create_index(VECTOR, config=IvfPq(distance_type="cosine", num_sub_vectors=max(1, self.meta.dimension // 8),
                                             target_partition_size=int(rows_per_partition)), replace=True)
        self.note_trained(int(vt.count_rows()))

    def has_index(self, name: str, column: str) -> bool:
        return name in self.names() and any(column in (ix.columns or [])
                                            for ix in self.db.open_table(name).list_indices())

    def has_word_index(self) -> bool:
        return self.has_index(self.passages_name, TEXT)

    def ensure_vector_ids(self) -> bool:
        """An index on the vectors table's passage_id. Without it, updating a few passages reads every vector into
        memory (gigabytes, once there are millions). Returns True if it had to be built."""
        from lancedb.index import BTree

        if self.vectors_name not in self.names():
            return False
        vt = self.vectors()
        if vt.count_rows() == 0 or any(PASSAGE_ID in (ix.columns or []) for ix in vt.list_indices()):
            return False
        vt.create_index(PASSAGE_ID, config=BTree(), replace=True)
        return True

    def _scalar_specs(self) -> list[tuple[str, Any]]:
        from lancedb.index import Bitmap, BTree, LabelList

        cols = self.scalar_columns
        return ([(c, BTree()) for c in cols.btree] + [(c, Bitmap()) for c in cols.bitmap]
                + [(c, LabelList()) for c in cols.label_list])

    def build_scalar_indexes(self, tbl: Any = None) -> None:
        """Indexes that let filtered (prefilter) searches skip non-matching rows."""
        tbl = self.passages() if tbl is None else tbl
        for col, cfg in self._scalar_specs():
            try:
                tbl.create_index(col, config=cfg, replace=True)
            except Exception as exc:  # scalar indexes are an optimisation only
                log.warning("scalar index on %s skipped: %s", col, exc)

    def ensure_scalar_indexes(self, columns: Sequence[str]) -> bool:
        """Build the indexes of these columns that are missing: for columns added to ``ScalarColumns`` after an
        index was first built, so an existing index gets them once. Returns True if any had to be built."""
        if not self.has_data():
            return False
        tbl = self.passages()
        have = {c for ix in tbl.list_indices() for c in (ix.columns or [])}
        missing = [(c, cfg) for c, cfg in self._scalar_specs() if c in columns and c not in have]
        for col, cfg in missing:
            tbl.create_index(col, config=cfg, replace=True)
        return bool(missing)

    def trained_on(self) -> int | None:
        """How many vectors the meaning-search index was trained on, if that was recorded."""
        try:
            return int(json.loads((self.path / TRAINED_FILE).read_text())["vectors"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def note_trained(self, n: int) -> None:
        (self.path / TRAINED_FILE).write_text(json.dumps({"vectors": n}))

    def refresh(self, full: bool = False) -> str:
        """Bring the indexes up to date after passages or vectors were written, and drop superseded versions.

        New rows are merged into the existing indexes (``tidy``). The word and filter indexes are built from
        scratch only when asked (``full``) or when there are none yet; the meaning-search index is trained again
        when ``vector_index_due``. Returns "built" or "merged"."""
        rebuilt = full or not self.has_word_index()
        if rebuilt:
            self.build_indexes(vectors=False)
        else:
            self.ensure_vector_ids()
        due = vector_index_due(self.stats()["vectors"], self.trained_on(), self.has_index(self.vectors_name, VECTOR),
                               minimum=self.min_vector_index_rows, growth=self.vector_index_growth)
        if (full or due) and self.build_vector_index():
            rebuilt = True
        self.tidy()
        return "built" if rebuilt else "merged"

    def unmerged(self) -> int:
        """Rows not yet in the word (BM25) or meaning-search index: added by an update that stopped before merging
        them."""
        out = 0
        for name, column in ((self.passages_name, TEXT), (self.vectors_name, VECTOR)):
            if name not in self.names():
                continue
            tbl = self.db.open_table(name)
            for ix in tbl.list_indices():
                if column in (ix.columns or []):
                    st = tbl.index_stats(ix.name)
                    out += int(st.num_unindexed_rows) if st else 0
        return out

    def tidy(self) -> None:
        """Merge new rows into the indexes, compact small files and drop superseded versions."""
        for name in (self.passages_name, self.vectors_name):
            if name in self.names():
                self.db.open_table(name).optimize(cleanup_older_than=KEEP_OLD_VERSIONS)

    # ---- reads --------------------------------------------------------------------------------------------------

    def search_words(self, query: str, where: str | None, limit: int) -> list[dict[str, Any]]:
        q = sanitise_query(query)
        if not q or self.passages_name not in self.names():
            return []
        search = self.passages().search(q, query_type="fts")
        if where:
            search = search.where(where, prefilter=True)
        found: list[dict[str, Any]] = search.limit(limit).to_list()
        return found

    def search_meaning(self, vector: Any, where: str | None, limit: int, nprobes: int | None = None,
                       refine_factor: int | None = None, columns: Sequence[str] | None = None,
                       exact: bool = False) -> list[dict[str, Any]]:
        """Nearest passages by meaning. The index compares compressed vectors, which misses about a third of the
        truly nearest 300; ``refine_factor`` re-checks that many times ``limit`` candidates against the full vectors,
        finding nearly all of them for a few milliseconds more."""
        import numpy as np

        def run() -> list[dict[str, Any]]:
            if self.vectors_name not in self.names():
                return []
            vt = self.vectors()
            if vt.count_rows() == 0:
                return []
            # the query in the table's own number type
            value_type = vt.schema.field(VECTOR).type.value_type
            q = np.asarray(vector, dtype=np.float32).astype(value_type.to_pandas_dtype())
            search = vt.search(q, vector_column_name=VECTOR).distance_type("cosine")
            if exact:  # every vector compared in full: slow, for checking the index
                search = search.bypass_vector_index()
            else:
                if nprobes:
                    search = search.nprobes(int(nprobes))
                if refine_factor:
                    search = search.refine_factor(int(refine_factor))
            if where:
                search = search.where(where, prefilter=True)
            # every column but the vector itself: 300 vectors as Python floats cost more than the search
            search = search.select([*(columns or self.schema.filter_names), "_distance"])
            found: list[dict[str, Any]] = search.limit(limit).to_list()
            return found

        return retry_once(run)

    def passages_for(self, passage_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        if not passage_ids:
            return {}
        rows = self.passages().search().where(_in(PASSAGE_ID, passage_ids)).limit(None).to_list()
        return {r[PASSAGE_ID]: r for r in rows}

    def rows_for_keys(self, keys: Sequence[str]) -> list[dict[str, Any]]:
        if not keys:
            return []
        # limit(None): an explicit huge limit makes LanceDB size buffers for it (GBs of RSS)
        cols = [*self.schema.filter_names, *self.schema.row_columns]
        rows: list[dict[str, Any]] = self.passages().search().where(_in(KEY, keys)).select(cols).limit(None).to_list()
        return rows

    def vectors_for_keys(self, keys: Sequence[str]) -> dict[str, Any]:
        """passage_id -> vector (32-bit floats), for the given source keys."""
        import numpy as np

        if not keys or self.vectors_name not in self.names():
            return {}
        found = self.vectors().search().where(_in(KEY, keys)).select([PASSAGE_ID, VECTOR]).limit(None).to_arrow()
        # straight from Arrow: a year's vectors as Python floats would take seconds and hundreds of MB
        flat = found[VECTOR].combine_chunks().flatten().to_numpy(zero_copy_only=False)
        return dict(zip(found[PASSAGE_ID].to_pylist(), flat.astype(np.float32).reshape(-1, self.meta.dimension),
                        strict=True))

    def embedded_ids(self, keys: Sequence[str]) -> set[str]:
        """The passages of the given source keys that have a vector."""
        if not keys or self.vectors_name not in self.names():
            return set()
        found = self.vectors().search().where(_in(KEY, keys)).select([PASSAGE_ID]).limit(None).to_arrow()
        return set(found[PASSAGE_ID].to_pylist())

    def versions(self) -> dict[str, int]:
        """Each table's current version: a write of any kind makes a new one."""
        return {name: int(self.db.open_table(name).version) for name in (self.passages_name, self.vectors_name)
                if name in self.names()}

    def stats(self) -> dict[str, int]:
        out = {"passages": 0, "vectors": 0}
        if self.passages_name in self.names():
            out["passages"] = int(self.passages().count_rows())
        if self.vectors_name in self.names():
            out["vectors"] = int(self.db.open_table(self.vectors_name).count_rows())
        return out
