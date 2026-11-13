"""The hashing embedder: the contract, and the same vectors as each site's own copy."""

from __future__ import annotations

import hashlib
import importlib.util

import numpy as np
import pytest

from adapters_sites import SITES, site_file
from wts_core.adapters.hashing import HashingEmbedder
from wts_core.ports import Embedder
from wts_core.testing.contracts import EmbedderContract

TEXTS = ["The council agreed the budget.", "Weekly bin collections will continue in the borough.",
         "HS2: the northern legs — costs, and the Minister's reply (2024)", "", "É ü ß naïve café", "word " * 400,
         "trial by jury"]


class TestHashingEmbedder(EmbedderContract):
    @pytest.fixture(params=[8, 64, 256])
    def embedder(self, request):
        return HashingEmbedder(request.param)


def test_it_is_an_embedder_with_the_sites_names_as_well_as_the_packages():
    e = HashingEmbedder(64)
    assert isinstance(e, Embedder)
    assert (e.id, e.name, e.dimension, e.dim, e.similarity_range) == ("hashing-64", "hashing-64", 64, 64, (0.0, 0.6))
    assert HashingEmbedder().dimension == 256


def test_vectors_are_32_bit_and_of_length_one():
    m = HashingEmbedder(64).embed_documents(TEXTS)
    assert m.dtype == np.float32 and m.shape == (len(TEXTS), 64)
    norms = np.linalg.norm(m, axis=1)
    assert norms[3] == 0.0  # no words: a row of noughts, not a division by nought
    assert np.allclose(np.delete(norms, 3), 1.0, atol=1e-6)
    assert HashingEmbedder(64).embed_documents([]).shape == (0, 64)


def test_texts_that_share_words_are_nearer_than_texts_that_do_not():
    e = HashingEmbedder(256)
    a, b, c = e.embed_documents(["the budget was agreed", "the council agreed the budget", "cycle lanes"])
    assert float(a @ b) > float(a @ c)
    assert np.array_equal(e.embed_query("the budget was agreed"), a)


def test_the_vectors_are_the_ones_the_sites_have_always_made():
    """The bytes of the vectors for a fixed list of texts, taken from Where MPs Stand's copy on 13 November 2026."""
    digest = hashlib.sha256(HashingEmbedder(256).embed_documents(TEXTS).tobytes()).hexdigest()
    assert digest == GOLDEN_256
    digest = hashlib.sha256(HashingEmbedder(64).embed_query(TEXTS[2]).tobytes()).hexdigest()
    assert digest == GOLDEN_64_QUERY


GOLDEN_256 = "20c9354ad95d740f88dedcb5f8e22d8aa1b46ca6eca2ec229bca00c9aec299ce"
GOLDEN_64_QUERY = "399064a91a35fdb4d21a32c6e3ba8b6b7286495d1641385610c906440f14ed18"


def site_embedders(name: str):
    """A site's own ``embed/base.py``, loaded from its file (it needs numpy and nothing of the site)."""
    spec = importlib.util.spec_from_file_location(f"{SITES[name][1]}_embed_base", site_file(name, "embed/base.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", list(SITES))
@pytest.mark.parametrize("dim", [8, 64, 256, 384])
def test_the_vectors_are_identical_to_the_sites_copy(name, dim):
    theirs, ours = site_embedders(name).HashingEmbedder(dim), HashingEmbedder(dim)
    assert (theirs.name, theirs.dim, theirs.similarity_range) == (ours.name, ours.dim, ours.similarity_range)
    assert np.array_equal(theirs.embed_documents(TEXTS), ours.embed_documents(TEXTS))
    assert theirs.embed_documents(TEXTS).dtype == ours.embed_documents(TEXTS).dtype
    for text in TEXTS:
        assert np.array_equal(theirs.embed_query(text), ours.embed_query(text))
    assert theirs.embed_documents([]).shape == ours.embed_documents([]).shape
