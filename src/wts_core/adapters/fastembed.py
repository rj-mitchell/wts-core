"""The embedder every site uses for search by meaning: a small open-source model run on the server.

``FastEmbedEmbedder`` runs the model through ONNX Runtime (fastembed). The weights are downloaded once from
Hugging Face into the site's ``data/models`` and their SHA-256 is part of the embedder's ``id``, so the model an
index was built with is pinned and can be checked. None of a site's data comes from, or goes to, Hugging Face.

This is the three sites' identical ``embed/base.py``; the vectors are the same for the same texts. ``fastembed`` and
numpy are imported when first used.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from wts_core.adapters.hashing import _normalise

__all__ = ["DOC_PREFIXES", "QUERY_PREFIXES", "FastEmbedEmbedder", "model_fingerprint"]

# Retrieval instruction prepended to queries (not documents) for models trained with one.
QUERY_PREFIXES = {
    "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
    "snowflake/snowflake-arctic-embed-xs": "Represent this sentence for searching relevant passages: ",
    "snowflake/snowflake-arctic-embed-s": "Represent this sentence for searching relevant passages: ",
    "nomic-ai/nomic-embed-text-v1.5": "search_query: ",
}
DOC_PREFIXES = {"nomic-ai/nomic-embed-text-v1.5": "search_document: "}


class FastEmbedEmbedder:
    """``ports.Embedder`` over fastembed.

    ``id`` is the model's name and, once the weights are on disk, the start of their fingerprint
    (``snowflake/snowflake-arctic-embed-xs@3f2a…``): what an index records, and what is compared when it is opened.
    The fingerprint covers every ``*.onnx`` file under ``cache_dir``, as Where MPs Stand's own check does, so keep
    one model in the folder: fetching a second changes the id of the first.
    """

    def __init__(self, model: str, cache_dir: Path, threads: int | None = None, batch_size: int = 64):
        # Once the model is on disk, never ask Hugging Face about it again: a slow or blocked network would
        # otherwise hold up the first search after every restart.
        if any(Path(cache_dir).rglob("*.onnx")):
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from fastembed import TextEmbedding  # optional dependency (the "ai" extra)

        self.name = model
        self.batch_size = batch_size
        # retrieval-tuned sentence embedders score unrelated passages around 0.5
        self.similarity_range = (0.5, 0.85)
        self._model = TextEmbedding(model, cache_dir=str(cache_dir), threads=threads)
        self.dim = self.dimension = len(next(iter(self._model.embed(["dimension probe"]))))
        self._qp = QUERY_PREFIXES.get(model, "")
        self._dp = DOC_PREFIXES.get(model, "")
        # after the model has loaded, so that a first run (which downloads the weights) has the same id as later ones
        self.fingerprint = model_fingerprint(cache_dir) if any(Path(cache_dir).rglob("*.onnx")) else ""
        self.id = f"{model}@{self.fingerprint[:16]}" if self.fingerprint else model

    def embed_documents(self, texts: Sequence[str]) -> Any:
        import numpy as np

        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vecs = list(self._model.embed([self._dp + t for t in texts], batch_size=self.batch_size))
        return _normalise(np.stack(vecs))

    def embed_query(self, text: str) -> Any:
        import numpy as np

        return _normalise(np.stack(list(self._model.embed([self._qp + text]))))[0]


def model_fingerprint(cache_dir: Path) -> str:
    """SHA-256 over the downloaded ONNX weights, recorded to pin the model in use."""
    h = hashlib.sha256()
    for p in sorted(Path(cache_dir).rglob("*.onnx")):
        h.update(p.name.encode())
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()
