"""Off-site copies in a Backblaze B2 bucket, behind ``ports.OffsiteStore``.

Uses B2's own API over HTTPS with ``httpx`` (no extra software), as the four sites' ``offsite.py`` each did: this is
their ``B2`` class. A site sets, in deploy/.env:

    <PREFIX>_B2_BUCKET=<bucket name>
    <PREFIX>_B2_KEY_ID=<keyID>
    <PREFIX>_B2_APPLICATION_KEY=<applicationKey>

The charity's sites can share one bucket and key: each site lists and deletes only the files with its own prefix
(``wts_core.ops``). The key should be limited to that one bucket. Each backup is uploaded with its SHA-1 checked by
B2. Nothing here ever prints the key.

Two things differ from the sites' class, and they change nothing a site does. The key is offered to Backblaze when
the store is first used, not when it is made, so that a store can be made from settings before anything is sent and
a refused key is recorded as a failed copy; ``close()`` ends that session, and the next use starts another. And
httpx's own errors (no network, an answer that is no answer) are raised as ``ops.OffsiteUnavailable`` with httpx's
words, so that ``wts_core.ops`` needn't know httpx to record them.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import urllib.parse
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from wts_core.ops.offsite import OffsiteError, OffsiteUnavailable
from wts_core.ports import StoredFile
from wts_core.settings import Site

if TYPE_CHECKING:
    import httpx

__all__ = ["B2Store", "configured", "how_to_set_up"]

_AUTHORIZE = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"
_SETTINGS = ("B2_BUCKET", "B2_KEY_ID", "B2_APPLICATION_KEY")


@dataclass
class _Session:
    """What Backblaze gave in exchange for the key: where to send requests, and the token they carry."""

    client: httpx.Client
    own: bool  # whether the client was made here, and so is closed here
    account: str
    api: str
    token: str
    bucket_id: str = ""


@contextlib.contextmanager
def _reaching() -> Iterator[None]:
    """A request that could not be made, or an answer that was no answer, is the store's error, in httpx's words."""
    import httpx

    try:
        yield
    except httpx.HTTPError as exc:
        raise OffsiteUnavailable(str(exc)) from exc


class B2Store:
    """One bucket (``ports.OffsiteStore``). ``client`` is for tests: an ``httpx.Client`` that is used and left open.
    ``env_prefix`` is the site's, so that a refused key names the settings to check."""

    def __init__(self, bucket: str, key_id: str, application_key: str, client: httpx.Client | None = None, *,
                 env_prefix: str | None = None) -> None:
        self.name = bucket
        self._key = (key_id, application_key)
        self._client = client
        self._env_prefix = env_prefix
        self._session: _Session | None = None

    def close(self) -> None:
        session, self._session = self._session, None
        if session is not None and session.own:
            session.client.close()

    def put(self, path: Path, tries: int = 3) -> StoredFile:
        """Upload one file under its own name. The whole file is read into memory."""
        data = Path(path).read_bytes()
        sha1 = hashlib.sha1(data).hexdigest()  # noqa: S324 (B2 checks uploads with SHA-1)
        last = ""
        with _reaching():
            session = self._open()
            for _ in range(tries):  # B2 asks for a fresh upload address after a failed upload
                target = self._call("b2_get_upload_url", {"bucketId": session.bucket_id})
                resp = session.client.post(target["uploadUrl"], content=data, headers={
                    "Authorization": target["authorizationToken"],
                    "X-Bz-File-Name": urllib.parse.quote(Path(path).name),
                    "Content-Type": "application/gzip", "X-Bz-Content-Sha1": sha1})
                if resp.status_code < 400:
                    return _stored(resp.json())
                last = f"{resp.status_code} {resp.text[:200]}"
        raise OffsiteError(f"upload failed: {last}")

    def delete(self, file: StoredFile) -> None:
        with _reaching():
            self._call("b2_delete_file_version", {"fileName": file.name, "fileId": file.id})

    def list(self, prefix: str) -> list[StoredFile]:
        """The files whose names start with ``prefix``, oldest first by name: one page, of at most 1,000."""
        with _reaching():
            session = self._open()
            files = self._call("b2_list_file_names", {"bucketId": session.bucket_id, "prefix": prefix,
                                                      "maxFileCount": 1000}).get("files") or []
        return sorted((_stored(f) for f in files), key=lambda f: f.name)

    def _open(self) -> _Session:
        """Offer the key and find the bucket, once for each session."""
        if self._session is not None:
            return self._session
        import httpx

        client = httpx.Client(timeout=300) if self._client is None else self._client
        try:
            resp = client.get(_AUTHORIZE, auth=self._key)
            if resp.status_code in (401, 403):
                names = (f"{self._env_prefix}_B2_KEY_ID and {self._env_prefix}_B2_APPLICATION_KEY"
                         if self._env_prefix else "the key's id and the application key")
                raise OffsiteError(f"Backblaze did not accept the key: check {names}")
            resp.raise_for_status()
            auth = resp.json()
            self._session = session = _Session(client, self._client is None, auth["accountId"], auth["apiUrl"],
                                               auth["authorizationToken"])
            allowed = auth.get("allowed") or {}
            if allowed.get("bucketName") and allowed["bucketName"] != self.name:
                raise OffsiteError(f"the key is for the bucket {allowed['bucketName']!r}, not {self.name!r}")
            session.bucket_id = allowed.get("bucketId") or self._find_bucket(session)
        except BaseException:
            self._session = None
            if self._client is None:
                client.close()
            raise
        return session

    def _find_bucket(self, session: _Session) -> str:
        found = self._call("b2_list_buckets", {"accountId": session.account, "bucketName": self.name}).get("buckets")
        if not found:
            raise OffsiteError(f"there is no bucket called {self.name!r} that this key can see")
        return str(found[0]["bucketId"])

    def _call(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        session = self._open()
        resp = session.client.post(f"{session.api}/b2api/v2/{name}", headers={"Authorization": session.token},
                                   json=body)
        if resp.status_code >= 400:
            raise OffsiteError(f"{name}: {resp.status_code} {resp.text[:200]}")
        answer: dict[str, Any] = resp.json()
        return answer


def _stored(f: Mapping[str, Any]) -> StoredFile:
    return StoredFile(name=f["fileName"], id=f.get("fileId") or "", size=int(f.get("contentLength") or 0))


def configured(site: Site, env: Mapping[str, str] | None = None, *,
               client: httpx.Client | None = None) -> B2Store | None:
    """The site's bucket, from ``<PREFIX>_B2_BUCKET``, ``_B2_KEY_ID`` and ``_B2_APPLICATION_KEY`` (each stripped), or
    None when any of the three is missing or empty: off-site copies are then "not set up". Nothing is sent yet."""
    env = os.environ if env is None else env
    bucket, key_id, application_key = ((env.get(site.env_name(name)) or "").strip() for name in _SETTINGS)
    if not (bucket and key_id and application_key):
        return None
    return B2Store(bucket, key_id, application_key, client, env_prefix=site.env_prefix)


def how_to_set_up(site: Site) -> str:
    """What ``ops.check_offsite`` says after "not set up: " for a site whose off-site store this is."""
    bucket, key_id, application_key = (site.env_name(name) for name in _SETTINGS)
    return f"add {bucket}, {key_id} and {application_key} to deploy/.env"
