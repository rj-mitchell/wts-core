"""An off-site store for tests: in memory, and able to fail when told to.

``MemoryOffsiteStore`` is a ``ports.OffsiteStore`` that keeps what it is given in a dictionary, so a site's tests
of its backup commands, and the package's of ``wts_core.ops``, can say what was stored, what was deleted and what
happens when the store refuses, without Backblaze or a network. It passes ``OffsiteStoreContract``
(``wts_core.testing.contracts``), as every real store's adapter must.
"""

from __future__ import annotations

from pathlib import Path

from wts_core.ports import OffsiteError, StoredFile

__all__ = ["MemoryOffsiteStore"]


class MemoryOffsiteStore:
    """A ``ports.OffsiteStore`` that keeps what it is given, and can be told to fail.

    ``files`` holds each file's bytes by name; ``closed`` counts the calls to ``close``. ``fail`` maps a method's
    name ("put", "list", "delete") to the error it then raises. ``can_delete=False`` is a key without the right to
    delete (the store refuses, as Backblaze does); ``newest_first=True`` answers ``list`` in the wrong order, for
    testing that nothing depends on a store's own."""

    def __init__(self, name: str = "wts-backups", *, can_delete: bool = True, newest_first: bool = False) -> None:
        self.name, self.can_delete, self.newest_first = name, can_delete, newest_first
        self.files: dict[str, bytes] = {}
        self.fail: dict[str, Exception] = {}
        self.closed = 0

    def put(self, path: Path) -> StoredFile:
        if "put" in self.fail:
            raise self.fail["put"]
        path = Path(path)
        self.files[path.name] = path.read_bytes()
        return StoredFile(path.name, f"id-{path.name}", len(self.files[path.name]))

    def list(self, prefix: str) -> list[StoredFile]:
        if "list" in self.fail:
            raise self.fail["list"]
        found = [StoredFile(n, f"id-{n}", len(self.files[n])) for n in sorted(self.files) if n.startswith(prefix)]
        return found[::-1] if self.newest_first else found

    def delete(self, file: StoredFile) -> None:
        if "delete" in self.fail:
            raise self.fail["delete"]
        if not self.can_delete:
            raise OffsiteError("b2_delete_file_version: 401 unauthorized")
        if file.name not in self.files:
            raise OffsiteError(f"there is no file called {file.name!r} in {self.name}")
        del self.files[file.name]

    def close(self) -> None:
        self.closed += 1
