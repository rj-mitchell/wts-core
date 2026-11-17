"""The embedder every site uses for search by meaning: a small open-source model run on the server.

``FastEmbedEmbedder`` runs the model through ONNX Runtime (fastembed). The weights are downloaded once from
Hugging Face into the site's ``data/models`` and their SHA-256 is part of the embedder's ``id``, so the model an
index was built with is pinned and can be checked. None of a site's data comes from, or goes to, Hugging Face.

Whose weights are fingerprinted. Only the files of the model named, where they can be told apart: the library
keeps each model it fetches in a folder of that model's own under the models folder, named after where it came
from (``models--Snowflake--snowflake-arctic-embed-xs``), and says where each model comes from
(``TextEmbedding.list_supported_models()``). So a second model fetched into the same folder (Where MPs Stand's
re-ranker) does not change the embedder's id, which would switch search by meaning off until every vector was
made again. Where the model's own folder cannot be found (a model the library does not list, or one it fetched
some other way) the whole models folder is fingerprinted, and then the rule is
one model to a folder: a folder that holds the weights of more than one is refused, with the folders named,
since hashing them together would tie this model's id to the other's files.

This is the three sites' identical ``embed/base.py``; the vectors are the same for the same texts. ``fastembed`` and
numpy are imported when first used.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from wts_core.adapters.hashing import _normalise

log = logging.getLogger(__name__)

__all__ = ["DOC_PREFIXES", "QUERY_PREFIXES", "FastEmbedEmbedder", "ModelFilesUnclear", "model_fingerprint",
           "model_fingerprints"]

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
    The fingerprint covers the ``*.onnx`` files of this model and no other's (``model_fingerprint`` says how they
    are told apart).

    Before 0.3.0 the fingerprint covered every ``*.onnx`` file under the models folder. Where that folder
    holds only the embedder's own files the two are the same. Where it holds more (a re-ranker beside the
    embedder or in a folder under it, a loose file), the id is now a different one, and an index stamped by an
    earlier version carries the old. So the old id, worked out from the folder as it is now, is given as
    ``earlier_ids``: ``adapters.lancedb.LanceIndex`` accepts an index stamped with it, once, and stamps it again
    with ``id``. Nothing is embedded again, and search by meaning does not go off. ``earlier_ids`` is given
    throughout 0.3.x and goes in 0.4.0, by when every index a site has opened is stamped anew.

    Making the embedder never fails for want of knowing which files are the model's. Where they cannot be
    told from another model's (``ModelFilesUnclear``: weights in more than one place, none of them the folder
    the library makes for this model), the id is the whole folder's, as before 0.3.0, an error in the log says
    so and what to do, and ``unclear`` holds the same words for a site's status page. Search carries on.
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
        self.fingerprint, earlier, self.unclear = model_fingerprints(cache_dir, model,
                                                                     sources=_sources(TextEmbedding, model))
        self.id = f"{model}@{self.fingerprint[:16]}" if self.fingerprint else model
        self.earlier_ids: tuple[str, ...] = tuple(f"{model}@{was[:16]}" for was in earlier)
        if self.unclear:
            log.error("the embedding model's id covers every model file under %s, as before 0.3.0: %s", cache_dir,
                      self.unclear)

    def embed_documents(self, texts: Sequence[str]) -> Any:
        import numpy as np

        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vecs = list(self._model.embed([self._dp + t for t in texts], batch_size=self.batch_size))
        return _normalise(np.stack(vecs))

    def embed_query(self, text: str) -> Any:
        import numpy as np

        return _normalise(np.stack(list(self._model.embed([self._qp + text]))))[0]


def _sources(library: Any, model: str) -> list[str]:
    """Where the library says it fetches ``model`` from (its public list of the models it supports): the name its
    folder under the models folder is made from. Nothing for a model it does not list, or a library that has no
    such list."""
    listed = getattr(library, "list_supported_models", None)
    if listed is None:
        return []
    try:
        return [str(source) for entry in listed() if str(entry.get("model", "")).lower() == model.lower()
                for source in [(entry.get("sources") or {}).get("hf")] if source]
    except Exception:  # the list is a convenience: without it the whole folder is fingerprinted, as before
        return []


def _holders(cache_dir: Path) -> list[Path]:
    """What directly under the models folder holds weights: each model's own folder, and the folder itself if
    weights lie loose in it."""
    cache_dir = Path(cache_dir)
    held = [d for d in sorted(cache_dir.iterdir()) if d.is_dir() and any(d.rglob("*.onnx"))] \
        if cache_dir.is_dir() else []
    return [*([cache_dir] if cache_dir.is_dir() and any(cache_dir.glob("*.onnx")) else []), *held]


class ModelFilesUnclear(RuntimeError):
    """The files of one model cannot be told from another's in a models folder: weights are held in more than
    one place under it, and none of them is the folder the library makes for the model asked about. Raised by
    ``model_fingerprint(cache_dir, model)``; ``FastEmbedEmbedder`` catches it and carries on with the whole
    folder's fingerprint, so it never stops a site from starting or searching."""


def _files_of(cache_dir: Path, model: str | None, sources: Iterable[str]) -> list[Path]:
    """The ``*.onnx`` files a fingerprint covers, in the order they are read: every one under ``cache_dir``, or
    with ``model`` that model's alone (``model_fingerprint`` says how they are found)."""
    cache_dir = Path(cache_dir)
    within = [cache_dir]
    if model is not None:
        wanted = {f"models--{name.replace('/', '--')}".lower() for name in (model, *sources)}
        holders = _holders(cache_dir)
        own = [d for d in holders if d != cache_dir and d.name.lower() in wanted]
        if own:
            within = own
        elif len(holders) > 1:
            raise ModelFilesUnclear(
                f"{cache_dir} holds the weights of more than one model ("
                + ", ".join("the folder itself" if d == cache_dir else d.name for d in holders)
                + f"), and none of them is the folder the library makes for {model}: the embedder's id depends "
                "on another model's files, and an index is out of date whenever those change. Give each model a "
                "models folder of its own (a re-ranker's beside the embedder's, not inside it)")
    return sorted(p for folder in within for p in folder.rglob("*.onnx"))


def _fingerprint(files: Iterable[Path]) -> str:
    h = hashlib.sha256()
    for p in files:
        h.update(p.name.encode())
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def model_fingerprint(cache_dir: Path, model: str | None = None, *, sources: Iterable[str] = ()) -> str:
    """SHA-256 over downloaded ONNX weights (each file's name, then its content, in the order of their paths),
    recorded to pin the model in use.

    With no ``model``: every ``*.onnx`` file under ``cache_dir``, as each site's own check did, and as every
    version before 0.3.0 made an embedder's id.

    With ``model``: the files of that model only. They are the ones in the folder the library made for it,
    ``models--<where it came from, with -- for each />``, where "where it came from" is the model's name or one of
    ``sources`` (what the library's own list gives; letters' case is passed over). For a models folder that holds
    one model this is the same fingerprint as before. Where no such folder is found, the whole of ``cache_dir`` is
    fingerprinted, but only if weights are held in one place under it: with more than one, this model's files
    cannot be told from another's, and ``ModelFilesUnclear`` (a ``RuntimeError``) says so, naming them."""
    return _fingerprint(_files_of(cache_dir, model, sources))


def model_fingerprints(cache_dir: Path, model: str, *, sources: Iterable[str] = ()) -> tuple[str, tuple[str, ...], str]:
    """What an embedder's id is made from, without loading the model: the fingerprint of ``model``'s own files;
    the fingerprints earlier versions would have given the same folder where they differ (the whole folder's:
    none where the folder holds only this model's files); and, where this model's files cannot be told from
    another's, why (the fingerprint is then the whole folder's, and there is no earlier one). Empty where no
    weights are on disk yet. For a check before a deploy that prints the id an index was stamped with beside
    the one it will be opened with."""
    everything = _files_of(Path(cache_dir), None, ())
    if not everything:
        return "", (), ""
    try:
        own = _files_of(Path(cache_dir), model, sources)
    except ModelFilesUnclear as exc:
        return _fingerprint(everything), (), str(exc)
    fingerprint = _fingerprint(own)
    if own == everything:
        return fingerprint, (), ""
    whole = _fingerprint(everything)
    return fingerprint, ((whole,) if whole != fingerprint else ()), ""
