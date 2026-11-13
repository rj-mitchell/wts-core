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
from wts_core.adapters.fastembed import DOC_PREFIXES, QUERY_PREFIXES, FastEmbedEmbedder, model_fingerprint
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


# --------------------------------------------------------------------------- the same as each site's own copy


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
