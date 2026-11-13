"""An embedder and an index for tests: both in memory, both keeping a note of everything they are given.

``RecordingEmbedder`` makes small deterministic vectors (texts that share words are near each other) and records
every text it embeds. ``MemoryIndex`` is a ``ports.VectorIndex`` that holds its rows and vectors in dictionaries
and records every write. Together they let a test say what reached the embedder and the index, and what never did:
half of how statements under the right of reply are shown to stay out of both.

Neither needs numpy: vectors are lists of floats.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from wts_core.ports import Embedder, IndexMeta, IndexOutOfDate

__all__ = ["MemoryIndex", "RecordingEmbedder"]

_TOKEN = re.compile(r"[a-z0-9]+")


class RecordingEmbedder:
    """A ``ports.Embedder`` whose vectors depend only on the words of the text (hashed into ``dimension`` places,
    scaled to length one), and which records what it was asked: ``documents`` and ``queries``, and ``texts`` for
    both together, in order."""

    def __init__(self, dimension: int = 8, id: str | None = None) -> None:
        self.dimension = dimension
        self.id = id or f"recording-{dimension}"
        self.documents: list[str] = []
        self.queries: list[str] = []
        self.texts: list[str] = []

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * self.dimension
        for word in _TOKEN.findall(text.lower()):
            h = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=8).digest(), "little")
            v[h % self.dimension] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.documents += texts
        self.texts += texts
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        self.texts.append(text)
        return self._vector(text)


def _floats(vector: Any) -> list[float]:
    return [float(x) for x in vector]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / norms if norms else 0.0


class MemoryIndex:
    """A ``ports.VectorIndex`` in memory.

    ``rows`` are the passages by ``passage_id`` and ``vectors`` their vectors; ``added`` is every row ever written,
    in order, whether or not it was later replaced, and ``calls`` the name of every method called. Search by words
    scores a passage by how many of the query's words its ``search_text`` has; search by meaning by cosine distance.

    A ``where`` clause is the store's own SQL, which this fake cannot read: each one is kept in ``wheres``, and
    applied only if the test gives ``matches``, a function of the clause and a row.

    ``reopen`` gives a second index over the same rows, as another process opening the same folder would have: with
    another embedder it raises ``IndexOutOfDate``, as every index must.
    """

    def __init__(self, embedder: Embedder | IndexMeta, *,
                 matches: Callable[[str, Mapping[str, Any]], bool] | None = None) -> None:
        self.meta = embedder if isinstance(embedder, IndexMeta) else IndexMeta(embedder.id, embedder.dimension)
        self.matches = matches
        self.rows: dict[str, dict[str, Any]] = {}
        self.vectors: dict[str, list[float]] = {}
        self.vector_rows: dict[str, dict[str, Any]] = {}
        self.added: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.wheres: list[str] = []

    def reopen(self, embedder: Embedder | IndexMeta) -> MemoryIndex:
        wanted = embedder if isinstance(embedder, IndexMeta) else IndexMeta(embedder.id, embedder.dimension)
        if wanted != self.meta:
            raise IndexOutOfDate(self.meta, wanted)
        other = MemoryIndex(self.meta, matches=self.matches)
        for name in ("rows", "vectors", "vector_rows", "added", "calls", "wheres"):
            setattr(other, name, getattr(self, name))
        return other

    def replace(self, keys: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
        self.calls.append("replace")
        for pid in [pid for pid, row in self.rows.items() if row.get("source_key") in keys]:
            del self.rows[pid]
        self._forget_vectors(keys)
        for row in rows:
            self.rows[row["passage_id"]] = dict(row)
            self.added.append(dict(row))

    def add_vectors(self, keys: Sequence[str], rows: Sequence[Mapping[str, Any]], vectors: Any) -> None:
        self.calls.append("add_vectors")
        new = [_floats(v) for v in vectors]
        wrong = next((len(v) for v in new if len(v) != self.meta.dimension), None)
        if wrong is not None:  # another model's vectors: never mixed in
            raise IndexOutOfDate(self.meta, replace(self.meta, dimension=wrong))
        if len(new) != len(rows):
            raise ValueError(f"{len(rows)} rows and {len(new)} vectors")
        self._forget_vectors(keys)
        for row, vector in zip(rows, new, strict=True):
            self.vectors[row["passage_id"]] = vector
            self.vector_rows[row["passage_id"]] = dict(row)
            self.added.append({**row, "vector": vector})

    def _forget_vectors(self, keys: Sequence[str]) -> None:
        for pid in [pid for pid, row in self.vector_rows.items() if row.get("source_key") in keys]:
            del self.vectors[pid], self.vector_rows[pid]

    def _kept(self, where: str | None, row: Mapping[str, Any]) -> bool:
        return not where or self.matches is None or self.matches(where, row)

    def search_words(self, query: str, where: str | None, limit: int) -> list[dict[str, Any]]:
        self.calls.append("search_words")
        if where:
            self.wheres.append(where)
        words = set(_TOKEN.findall(query.lower()))
        scored = []
        for row in self.rows.values():
            score = len(words & set(_TOKEN.findall(str(row.get("search_text") or row.get("text") or "").lower())))
            if score and self._kept(where, row):
                scored.append({**row, "_score": float(score)})
        return sorted(scored, key=lambda r: -r["_score"])[:limit]

    def search_meaning(self, vector: Any, where: str | None, limit: int) -> list[dict[str, Any]]:
        self.calls.append("search_meaning")
        if where:
            self.wheres.append(where)
        q = _floats(vector)
        if len(q) != self.meta.dimension:
            raise IndexOutOfDate(self.meta, replace(self.meta, dimension=len(q)))
        found = [{**self.vector_rows[pid], "_distance": 1.0 - _cosine(q, v)} for pid, v in self.vectors.items()
                 if self._kept(where, self.vector_rows[pid])]
        return sorted(found, key=lambda r: r["_distance"])[:limit]

    def build_indexes(self) -> None:
        self.calls.append("build_indexes")

    def tidy(self) -> None:
        self.calls.append("tidy")
