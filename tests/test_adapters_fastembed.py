"""The fastembed embedder, with the library faked: no model is downloaded in tests.

The fake ``TextEmbedding`` takes what the real one takes from the sites' code (the model's name, ``cache_dir`` and
``threads``; ``embed(texts, batch_size=…)``, which yields one vector for each text) and makes vectors that are not of
length one, so the test can see them normalised.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import os
import sys
from types import ModuleType

import numpy as np
import pytest

from adapters_sites import SITES, site_file
from wts_core.adapters.fastembed import (
    DOC_PREFIXES,
    QUERY_PREFIXES,
    FastEmbedEmbedder,
    ModelFilesUnclear,
    model_fingerprint,
    model_fingerprints,
)
from wts_core.ports import Embedder
from wts_core.testing.contracts import EmbedderContract

MODEL = "snowflake/snowflake-arctic-embed-xs"  # every site's [embedding] model


class FakeTextEmbedding:
    made: list[FakeTextEmbedding] = []

    def __init__(self, model_name, cache_dir=None, threads=None):
        self.model_name, self.cache_dir, self.threads = model_name, cache_dir, threads
        self.calls: list[tuple[list[str], int | None]] = []
        FakeTextEmbedding.made.append(self)

    def embed(self, documents, batch_size=256):
        self.calls.append((list(documents), batch_size))
        for text in documents:
            seed = int.from_bytes(hashlib.blake2b(text.encode(), digest_size=4).digest(), "little")
            yield np.random.default_rng(seed).standard_normal(12).astype(np.float32) * 3.0


@pytest.fixture(autouse=True)
def fake_library(monkeypatch):
    module = ModuleType("fastembed")
    module.TextEmbedding = FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", module)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    FakeTextEmbedding.made = []


class TestFastEmbedEmbedder(EmbedderContract):
    @pytest.fixture
    def embedder(self, tmp_path):
        return FastEmbedEmbedder(MODEL, tmp_path, batch_size=8)


def test_the_library_is_called_as_the_sites_call_it(tmp_path):
    e = FastEmbedEmbedder(MODEL, tmp_path, threads=2, batch_size=8)
    (model,) = FakeTextEmbedding.made
    assert (model.model_name, model.cache_dir, model.threads) == (MODEL, str(tmp_path), 2)
    assert model.calls == [(["dimension probe"], 256)]  # the dimension is found by embedding a probe
    assert isinstance(e, Embedder)
    assert (e.name, e.dimension, e.dim, e.batch_size, e.similarity_range) == (MODEL, 12, 12, 8, (0.5, 0.85))
    e.embed_documents(["one", "two"])
    assert model.calls[-1] == (["one", "two"], 8)
    assert FastEmbedEmbedder(MODEL, tmp_path).batch_size == 64


def test_the_real_library_takes_those_arguments():
    """The fake is only as good as its likeness: the installed fastembed's own signatures are read."""
    del sys.modules["fastembed"]
    TextEmbedding = pytest.importorskip("fastembed").TextEmbedding

    made = list(inspect.signature(TextEmbedding.__init__).parameters)
    assert made[1:4] == ["model_name", "cache_dir", "threads"]
    embed = inspect.signature(TextEmbedding.embed).parameters
    assert list(embed)[1] == "documents" and "batch_size" in embed
    assert any(m["model"] == MODEL and m["dim"] == 384 for m in TextEmbedding.list_supported_models())


def test_vectors_are_32_bit_and_of_length_one(tmp_path):
    e = FastEmbedEmbedder(MODEL, tmp_path)
    m = e.embed_documents(["one", "two", "three"])
    assert m.dtype == np.float32 and m.shape == (3, 12)
    assert np.allclose(np.linalg.norm(m, axis=1), 1.0, atol=1e-6)
    q = e.embed_query("one")
    assert q.dtype == np.float32 and q.shape == (12,) and np.linalg.norm(q) == pytest.approx(1.0, abs=1e-6)
    assert e.embed_documents([]).shape == (0, 12) and e.embed_documents([]).dtype == np.float32


@pytest.mark.parametrize("model", [MODEL, "BAAI/bge-small-en-v1.5", "nomic-ai/nomic-embed-text-v1.5", "another/model"])
def test_a_models_own_instruction_goes_before_a_query_and_not_before_a_document(tmp_path, model):
    e = FastEmbedEmbedder(model, tmp_path)
    e.embed_query("bins")
    e.embed_documents(["bins"])
    calls = FakeTextEmbedding.made[0].calls
    assert calls[-2][0] == [QUERY_PREFIXES.get(model, "") + "bins"]
    assert calls[-1][0] == [DOC_PREFIXES.get(model, "") + "bins"]


def test_the_instructions_are_the_ones_the_models_were_trained_with():
    assert QUERY_PREFIXES[MODEL] == "Represent this sentence for searching relevant passages: "
    assert QUERY_PREFIXES["nomic-ai/nomic-embed-text-v1.5"] == "search_query: "
    assert DOC_PREFIXES == {"nomic-ai/nomic-embed-text-v1.5": "search_document: "}


def weights(folder, name="model.onnx", content=b"weights"):
    path = folder / "models--snowflake--snowflake-arctic-embed-xs" / "onnx" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_the_id_is_the_models_name_and_once_the_weights_are_there_their_fingerprint(tmp_path):
    assert FastEmbedEmbedder(MODEL, tmp_path).id == MODEL  # nothing on disk to pin (the library is faked)
    weights(tmp_path)
    e = FastEmbedEmbedder(MODEL, tmp_path)
    assert e.fingerprint == model_fingerprint(tmp_path) and len(e.fingerprint) == 64
    assert e.id == f"{MODEL}@{e.fingerprint[:16]}"
    assert FastEmbedEmbedder(MODEL, tmp_path).id == e.id  # the same weights: the same id, every start
    weights(tmp_path, content=b"other weights")
    assert FastEmbedEmbedder(MODEL, tmp_path).id != e.id  # changed weights: an index built before is out of date


def test_a_first_run_that_fetches_the_weights_has_the_id_later_runs_have(tmp_path, monkeypatch):
    class Downloading(FakeTextEmbedding):
        def __init__(self, model_name, cache_dir=None, threads=None):
            super().__init__(model_name, cache_dir, threads)
            weights(tmp_path)

    monkeypatch.setattr(sys.modules["fastembed"], "TextEmbedding", Downloading)
    first = FastEmbedEmbedder(MODEL, tmp_path)
    assert "HF_HUB_OFFLINE" not in os.environ  # nothing was on disk, so Hugging Face had to be asked
    assert first.id == FastEmbedEmbedder(MODEL, tmp_path).id != MODEL


def test_once_the_model_is_on_disk_hugging_face_is_not_asked_again(tmp_path, monkeypatch):
    FastEmbedEmbedder(MODEL, tmp_path)
    assert "HF_HUB_OFFLINE" not in os.environ
    weights(tmp_path)
    FastEmbedEmbedder(MODEL, tmp_path)
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")  # an explicit choice is kept
    FastEmbedEmbedder(MODEL, tmp_path)
    assert os.environ["HF_HUB_OFFLINE"] == "0"


def test_the_fingerprint_covers_every_weights_file_by_name_and_content(tmp_path):
    empty = model_fingerprint(tmp_path)
    assert empty == hashlib.sha256().hexdigest()
    weights(tmp_path)
    one = model_fingerprint(tmp_path)
    (tmp_path / "notes.txt").write_text("not weights")
    assert model_fingerprint(tmp_path) == one != empty
    weights(tmp_path, "model_optimized.onnx")
    assert model_fingerprint(tmp_path) != one
    expected = hashlib.sha256(b"model.onnx" + b"weights" + b"model_optimized.onnx" + b"weights").hexdigest()
    assert model_fingerprint(tmp_path) == expected


def test_a_second_model_fetched_into_the_same_folder_does_not_change_the_embedders_id(tmp_path, monkeypatch):
    """Found by Where MPs Stand's adoption: the fingerprint covered the whole models folder, so fetching its
    re-ranker there would have changed the embedder's id, and every index would have been out of date. Only the
    files of the model named are fingerprinted, where the library's own folder for it can be found."""
    class Listing(FakeTextEmbedding):
        @classmethod
        def list_supported_models(cls):
            return [{"model": "another/model", "sources": {"hf": "Another/model-onnx"}},
                    {"model": MODEL, "sources": {"hf": "Snowflake/snowflake-arctic-embed-xs", "url": None}}]

    monkeypatch.setattr(sys.modules["fastembed"], "TextEmbedding", Listing)
    weights(tmp_path)
    alone = FastEmbedEmbedder(MODEL, tmp_path)
    assert alone.fingerprint == model_fingerprint(tmp_path)  # one model in the folder: what it always was
    other = tmp_path / "models--Xenova--ms-marco-MiniLM-L-6-v2" / "onnx" / "model.onnx"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"a re-ranker's weights")
    assert model_fingerprint(tmp_path) != alone.fingerprint  # the whole folder would have changed
    assert FastEmbedEmbedder(MODEL, tmp_path).id == alone.id  # the embedder's own files have not
    other.write_bytes(b"the re-ranker, updated")
    assert FastEmbedEmbedder(MODEL, tmp_path).id == alone.id
    weights(tmp_path, content=b"the embedder's weights, changed")
    assert FastEmbedEmbedder(MODEL, tmp_path).id != alone.id  # its own still pin it


def test_the_models_own_folder_is_found_by_where_the_library_says_it_came_from(tmp_path, monkeypatch):
    """The library names a model's folder after its source, which need not be the name a site's settings give
    (nor in the same case)."""
    class Listing(FakeTextEmbedding):
        @classmethod
        def list_supported_models(cls):
            return [{"model": "BAAI/bge-small-en-v1.5", "sources": {"hf": "Qdrant/bge-small-en-v1.5-onnx-q"}}]

    monkeypatch.setattr(sys.modules["fastembed"], "TextEmbedding", Listing)
    own = tmp_path / "models--qdrant--bge-small-en-v1.5-onnx-Q" / "snapshots" / "abc" / "model_optimized.onnx"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"weights")
    weights(tmp_path, content=b"another model's")
    e = FastEmbedEmbedder("BAAI/bge-small-en-v1.5", tmp_path)
    assert e.fingerprint == hashlib.sha256(b"model_optimized.onnx" + b"weights").hexdigest()
    assert e.fingerprint == model_fingerprint(tmp_path, "BAAI/bge-small-en-v1.5",
                                              sources=["Qdrant/bge-small-en-v1.5-onnx-q"])


def test_a_folder_of_several_models_none_of_them_this_ones_never_stops_the_embedder_being_made(tmp_path, caplog):
    """Where the model's own files cannot be told apart, asking for its fingerprint is refused by name
    (``ModelFilesUnclear``, a ``RuntimeError``). The embedder itself is still made: a first version raised from
    its constructor, which the sites' engines catch as "no embedder", and search by meaning went off without a
    word of why. Its id is then the whole folder's, as before 0.3.0, and it says so."""
    import logging

    weights(tmp_path)
    assert FastEmbedEmbedder("a-model/nobody-lists", tmp_path).fingerprint == model_fingerprint(tmp_path)  # one: taken
    other = tmp_path / "fast-bge-small-en" / "model.onnx"  # fetched another way: no folder of the library's naming
    other.parent.mkdir()
    other.write_bytes(b"weights")
    with pytest.raises(ModelFilesUnclear, match="holds the weights of more than one model .fast-bge-small-en, "
                                                "models--snowflake--snowflake-arctic-embed-xs.*Give each model a "
                                                "models folder of its own") as unclear:
        model_fingerprint(tmp_path, "a-model/nobody-lists")
    assert isinstance(unclear.value, RuntimeError)
    with caplog.at_level(logging.ERROR, logger="wts_core.adapters.fastembed"):
        made = FastEmbedEmbedder("a-model/nobody-lists", tmp_path)
    assert made.id == f"a-model/nobody-lists@{model_fingerprint(tmp_path)[:16]}" and made.earlier_ids == ()
    assert made.unclear == str(unclear.value) and "as before 0.3.0" in caplog.text and made.unclear in caplog.text
    known = FastEmbedEmbedder(MODEL, tmp_path)  # the one whose folder is known has its own files' id
    assert known.id.startswith(MODEL + "@") and known.unclear == ""


OWN = "models--Snowflake--snowflake-arctic-embed-xs"
EMBEDDER = {f"{OWN}/snapshots/abc123/onnx/model.onnx": b"EMBEDDER WEIGHTS"}
RERANKER = {"models--Xenova--ms-marco-MiniLM-L-6-v2/snapshots/def456/onnx/model.onnx": b"RERANKER WEIGHTS"}
FAST = {"fast-snowflake-arctic-embed-xs/model_optimized.onnx": b"EMBEDDER WEIGHTS"}
# The layouts of a models folder the independent review of 0.3.0 tried, and whether the id the first version of
# 0.3.0 gave the embedder was the id 0.2.1 had stamped the index with: where it was not, search by meaning went
# off on the upgrade until every vector was made again, and the changelog said "nothing to do".
LAYOUTS: dict[str, tuple[dict[str, bytes], str]] = {
    "one model, in the library's own folder": (EMBEDDER, "same"),
    "the embedder and a re-ranker side by side": ({**EMBEDDER, **RERANKER}, "earlier"),
    "the embedder's folder in another letter case": (
        {f"{OWN.lower()}/snapshots/abc/onnx/model.onnx": b"EMBEDDER WEIGHTS"}, "same"),
    "one model fetched the library's other way": (FAST, "same"),
    "fetched the other way, and a re-ranker": ({**FAST, **RERANKER}, "unclear"),
    "the embedder's folder and a loose file": ({**EMBEDDER, "old-model.onnx": b"SOMETHING ELSE"}, "earlier"),
    "two revisions of the embedder in its folder": (
        {**EMBEDDER, f"{OWN}/snapshots/zzz999/onnx/model.onnx": b"EMBEDDER WEIGHTS v2"}, "same"),
    "the embedder, and a re-ranker in a folder under the models folder": (
        {**EMBEDDER, **{"reranker/" + name: content for name, content in RERANKER.items()}}, "earlier"),
}


def laid_out(folder, files):
    for name, content in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
    return folder


@pytest.mark.parametrize("layout", list(LAYOUTS))
def test_an_index_stamped_by_an_earlier_version_is_never_out_of_date_for_the_change_of_id(tmp_path, layout):
    """Whatever else lies in the models folder, the id 0.2.1 stamped an index with (every model file under the
    folder) is either the embedder's id still, or among its ``earlier_ids``, which the index accepts once."""
    files, how = LAYOUTS[layout]
    folder = laid_out(tmp_path, files)
    stamped_by_0_2_1 = f"{MODEL}@{model_fingerprint(folder)[:16]}"
    fingerprint, earlier, unclear = model_fingerprints(folder, MODEL, sources=["Snowflake/snowflake-arctic-embed-xs"])
    made = FastEmbedEmbedder(MODEL, folder)  # (the fake library lists no sources: the model's own name finds it)
    assert made.fingerprint == fingerprint and bool(made.unclear) == bool(unclear) == (how == "unclear")
    assert stamped_by_0_2_1 in (made.id, *made.earlier_ids)
    assert {"same": made.id == stamped_by_0_2_1 and made.earlier_ids == (),
            "earlier": made.id != stamped_by_0_2_1 and made.earlier_ids == (stamped_by_0_2_1,),
            "unclear": made.id == stamped_by_0_2_1 and made.earlier_ids == ()}[how]
    if how == "earlier":  # and the id is now the embedder's own files', whatever becomes of the others
        assert made.fingerprint == model_fingerprint(laid_out(tmp_path / "alone", EMBEDDER))
        assert tuple(f"{MODEL}@{was[:16]}" for was in earlier) == made.earlier_ids


def test_with_no_weights_on_disk_there_is_no_fingerprint_and_no_earlier_one(tmp_path):
    assert model_fingerprints(tmp_path, MODEL) == ("", (), "")
    assert model_fingerprints(tmp_path / "not-there", MODEL) == ("", (), "")


def test_the_real_library_lists_where_each_model_comes_from():
    del sys.modules["fastembed"]
    TextEmbedding = pytest.importorskip("fastembed").TextEmbedding
    from wts_core.adapters.fastembed import _sources

    assert _sources(TextEmbedding, MODEL) == ["Snowflake/snowflake-arctic-embed-xs"]
    assert _sources(TextEmbedding, "a-model/nobody-lists") == []


# The same as each site's own copy


def site_module(name: str):
    spec = importlib.util.spec_from_file_location(f"{SITES[name][1]}_embed_base", site_file(name, "embed/base.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", list(SITES))
@pytest.mark.parametrize("model", [MODEL, "nomic-ai/nomic-embed-text-v1.5"])
def test_the_vectors_and_the_calls_are_the_sites_own(tmp_path, name, model):
    theirs_module = site_module(name)
    assert (theirs_module.QUERY_PREFIXES, theirs_module.DOC_PREFIXES) == (QUERY_PREFIXES, DOC_PREFIXES)
    weights(tmp_path)
    assert theirs_module.model_fingerprint(tmp_path) == model_fingerprint(tmp_path)
    theirs = theirs_module.FastEmbedEmbedder(model, tmp_path, threads=1, batch_size=8)
    ours = FastEmbedEmbedder(model, tmp_path, threads=1, batch_size=8)
    texts = ["The council agreed the budget.", "Weekly bin collections will continue.", ""]
    assert np.array_equal(theirs.embed_documents(texts), ours.embed_documents(texts))
    assert np.array_equal(theirs.embed_query(texts[0]), ours.embed_query(texts[0]))
    assert (theirs.name, theirs.dim, theirs.similarity_range) == (ours.name, ours.dim, ours.similarity_range)
    their_library, our_library = FakeTextEmbedding.made
    assert (their_library.model_name, their_library.cache_dir, their_library.threads, their_library.calls) == \
        (our_library.model_name, our_library.cache_dir, our_library.threads, our_library.calls)


def _index_at(folder, embedder):
    pytest.importorskip("lancedb")
    import pyarrow as pa

    from wts_core.adapters.lancedb import IndexSchema, LanceIndex, ScalarColumns

    text = pa.string()
    return LanceIndex(folder, embedder,
                      schema=IndexSchema(filter_fields=[(n, text) for n in ("passage_id", "record_id", "source_key")],
                                         passage_fields=[("text", text), ("search_text", text)]),
                      scalar_columns=ScalarColumns(btree=("passage_id", "source_key", "record_id"), bitmap=()))


def _stamped_by_0_2_1(tmp_path, files):
    """A models folder laid out so, and an index stamped as 0.2.1 stamped one: with the whole folder's id."""
    from types import SimpleNamespace

    models = laid_out(tmp_path / "models", files)
    was = SimpleNamespace(id=f"{MODEL}@{model_fingerprint(models)[:16]}", dimension=12)
    index = _index_at(tmp_path / "index", was)
    rows = [{"passage_id": f"p{n}", "record_id": f"r{n}", "source_key": "k", "text": f"text {n}",
             "search_text": f"text {n}"} for n in range(3)]
    index.replace(["k"], rows)
    index.add_vectors(["k"], rows, np.ones((3, 12), dtype=np.float32))
    return models


def _moved_out(models, files):
    """The models folder with only these files left in it."""
    import shutil

    shutil.rmtree(models)
    return laid_out(models, files)


def test_the_index_is_opened_once_on_this_version_before_the_models_folder_is_touched(tmp_path):
    """Found by the second independent review of 0.3.0: the advice "give each model a folder of its own when
    convenient" could itself put search by meaning off. The earlier id is worked out from the folder AS IT IS
    NOW, so it is the id 0.2.1 stamped only while the folder still holds what it held then. The order that is
    safe, and the one that is not (CHANGELOG.md, 0.3.0)."""
    from wts_core.ports import IndexOutOfDate

    # not safe: the re-ranker is moved out before the index has been opened on this version
    models = _stamped_by_0_2_1(tmp_path / "moved-first", {**EMBEDDER, **RERANKER})
    _moved_out(models, EMBEDDER)
    with pytest.raises(IndexOutOfDate):
        _index_at(tmp_path / "moved-first" / "index", FastEmbedEmbedder(MODEL, models))
    # safe: opened once (and stamped again with the embedder's own files' id), and then moved out
    models = _stamped_by_0_2_1(tmp_path / "opened-first", {**EMBEDDER, **RERANKER})
    _index_at(tmp_path / "opened-first" / "index", FastEmbedEmbedder(MODEL, models))
    _moved_out(models, EMBEDDER)
    assert _index_at(tmp_path / "opened-first" / "index", FastEmbedEmbedder(MODEL, models)).stats()["vectors"] == 3
    # the same if the re-ranker's own files change (a newer re-ranker): before the first opening it is out of
    # date, after it nothing of the re-ranker's matters
    models = _stamped_by_0_2_1(tmp_path / "changed-first", {**EMBEDDER, **RERANKER})
    laid_out(models, dict.fromkeys(RERANKER, b"A NEWER RE-RANKER"))
    with pytest.raises(IndexOutOfDate):
        _index_at(tmp_path / "changed-first" / "index", FastEmbedEmbedder(MODEL, models))


def test_where_the_models_files_cannot_be_told_apart_separating_them_means_making_the_vectors_again(tmp_path):
    """In the unclear case the id is the whole folder's, before and after the first opening: there is no id of
    the embedder's own files to stamp the index with. So giving each model its folder, at any time, changes the
    id, and the vectors have to be made again. The embedder's ``unclear`` says a site is in this case."""
    from wts_core.ports import IndexOutOfDate

    models = _stamped_by_0_2_1(tmp_path, {**FAST, **RERANKER})
    unclear = FastEmbedEmbedder(MODEL, models)
    assert unclear.unclear and unclear.earlier_ids == ()
    assert _index_at(tmp_path / "index", unclear).stats()["vectors"] == 3  # it opens, on the whole folder's id
    _moved_out(models, FAST)  # each model given a folder of its own: this one's are now the only files here
    alone = FastEmbedEmbedder(MODEL, models)
    assert alone.unclear == "" and alone.id != unclear.id
    with pytest.raises(IndexOutOfDate):
        _index_at(tmp_path / "index", alone)
