"""The off-site store for tests, and the contract every off-site store keeps: the memory store passes it, and so
does the Backblaze adapter against a pretend Backblaze."""

from __future__ import annotations

import pytest

from test_adapters_b2 import FakeB2
from test_ops_sites import COUNTRIES
from wts_core.adapters.b2 import configured
from wts_core.ports import OffsiteError, OffsiteStore, StoredFile
from wts_core.testing import MemoryOffsiteStore
from wts_core.testing.contracts import OffsiteStoreContract


class TestMemoryOffsiteStore(OffsiteStoreContract):
    @pytest.fixture
    def store(self) -> OffsiteStore:
        return MemoryOffsiteStore()


class TestB2Store(OffsiteStoreContract):
    @pytest.fixture
    def store(self) -> OffsiteStore:
        store = configured(COUNTRIES.site, COUNTRIES.env(), client=FakeB2().client())
        assert store is not None
        return store


def test_a_store_that_breaks_the_contract_fails_it(tmp_path):
    """The contract is a test, not a formality: a store that lists every site's files under any prefix fails."""

    class ListsEverything(MemoryOffsiteStore):
        def list(self, prefix: str) -> list[StoredFile]:
            return super().list("")

    with pytest.raises(AssertionError):
        OffsiteStoreContract().test_only_files_whose_names_start_with_the_prefix_are_listed(ListsEverything(),
                                                                                           tmp_path)


def test_the_memory_store_can_be_told_to_fail(tmp_path):
    store = MemoryOffsiteStore("a-bucket", can_delete=False, newest_first=True)
    assert store.name == "a-bucket"
    for day in (11, 12):
        store.put(OffsiteStoreContract.backup(tmp_path, f"wcs-state-2026-11-{day}.sqlite.gz"))
    newest, oldest = store.list("wcs-state-")
    assert newest.name > oldest.name  # the wrong way round, as asked: nothing may depend on a store's order
    with pytest.raises(OffsiteError, match="401 unauthorized"):  # a key without the right to delete
        store.delete(oldest)
    store.can_delete = True
    store.delete(oldest)
    with pytest.raises(OffsiteError, match="there is no file called"):
        store.delete(oldest)
    store.fail["put"] = OffsiteError("upload failed: 503")
    with pytest.raises(OffsiteError, match="upload failed: 503"):
        store.put(tmp_path / "wcs-state-2026-11-12.sqlite.gz")
    store.close()
    assert store.closed == 1 and sorted(store.files) == ["wcs-state-2026-11-12.sqlite.gz"]
