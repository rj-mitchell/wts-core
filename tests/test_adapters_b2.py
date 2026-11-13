"""Off-site copies in Backblaze B2 (a simulated B2; no real key is used): the four sites' tests of their ``offsite.py``,
through ``ops.send_offsite`` and the adapter, for each site's names; and the comparisons with each site's own code
(the same requests, the same ``offsite.json``, the same errors)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from test_ops_sites import SITES, each_site, freeze_their_clock, own_code
from wts_core.adapters.b2 import B2Store, configured, how_to_set_up
from wts_core.ops import OffsiteError, OffsiteUnavailable, check_offsite, send_offsite
from wts_core.ports import OffsiteStore, StoredFile
from wts_core.testing import FixedClock

WHEN = datetime(2026, 10, 12, 3, 31, 7, tzinfo=UTC)


class FakeB2:
    """Backblaze, as far as the sites use it (from their tests), keeping a note of every request made."""

    def __init__(self, bucket="wts-backups", fail_uploads=0, can_delete=True, limited=True, buckets=("wts-backups",),
                 authorize=200, down_at: str | None = None):
        self.bucket, self.fail_uploads, self.can_delete, self.limited = bucket, fail_uploads, can_delete, limited
        self.buckets, self.authorize, self.down_at = buckets, authorize, down_at
        self.files: dict[str, bytes] = {}
        self.requests: list[tuple[str, str, dict[str, str], bytes]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        kept = ("authorization", "x-bz-file-name", "content-type", "x-bz-content-sha1")
        self.requests.append((request.method, str(request.url), {k: request.headers[k] for k in kept
                                                                  if k in request.headers}, request.content))
        if self.down_at and path.endswith(self.down_at):
            raise httpx.ConnectError("[Errno 101] Network is unreachable", request=request)
        if path.endswith("b2_authorize_account"):
            if request.headers.get("authorization") != httpx.BasicAuth("kid", "secret")._auth_header:
                return httpx.Response(401, request=request)
            if self.authorize != 200:
                return httpx.Response(self.authorize, request=request)
            allowed = {"bucketId": "b1", "bucketName": self.bucket} if self.limited else {}
            return httpx.Response(200, json={"accountId": "acc", "apiUrl": "https://api.b2.test",
                                             "authorizationToken": "tok", "allowed": allowed})
        assert request.headers.get("authorization") in ("tok", "up"), "every call carries a token"
        body = json.loads(request.content or b"{}") if path.startswith("/b2api") else {}
        if path.endswith("b2_list_buckets"):
            assert body["accountId"] == "acc"
            return httpx.Response(200, json={"buckets": [{"bucketId": f"id-{n}", "bucketName": n}
                                                         for n in self.buckets if n == body["bucketName"]]})
        if path.endswith("b2_get_upload_url"):
            return httpx.Response(200, json={"uploadUrl": "https://up.b2.test/upload", "authorizationToken": "up"})
        if path == "/upload":
            if self.fail_uploads:
                self.fail_uploads -= 1
                return httpx.Response(503, text="service unavailable")
            assert request.headers["x-bz-content-sha1"] == hashlib.sha1(request.content).hexdigest()  # noqa: S324
            self.files[request.headers["x-bz-file-name"]] = request.content
            return httpx.Response(200, json={"fileName": request.headers["x-bz-file-name"], "fileId": "new",
                                             "contentLength": len(request.content)})
        if path.endswith("b2_list_file_names"):
            return httpx.Response(200, json={"files": [{"fileName": n, "fileId": f"id-{n}",
                                                        "contentLength": len(self.files[n])}
                                                       for n in sorted(self.files) if n.startswith(body["prefix"])]})
        if path.endswith("b2_delete_file_version"):
            if not self.can_delete:
                return httpx.Response(401, json={"code": "unauthorized"})
            del self.files[body["fileName"]]
            return httpx.Response(200, json={})
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def calls(self) -> list[str]:
        return [url.rsplit("/", 1)[-1] for _, url, _, _ in self.requests]


def archive(folder: Path, site, day: str) -> Path:
    p = folder / site.archive_name(datetime.fromisoformat(day).replace(tzinfo=UTC))
    p.write_bytes(f"backup {day}".encode())
    return p


def store_for(site, fake: FakeB2, **env: str) -> B2Store:
    store = configured(site.site, site.env(**env), client=fake.client())
    assert store is not None
    return store


def send(site, fake: FakeB2, path: Path, **more: Any) -> dict[str, Any]:
    return send_offsite(path, store_for(site, fake), site.spec, clock=FixedClock(WHEN), **more)


# ---- the sites' tests --------------------------------------------------------------------------------------------


@each_site
def test_not_set_up_does_nothing(site, tmp_path):
    assert configured(site.site, {}) is None
    for missing in site.env():  # all three are needed, and a blank one is a missing one
        assert configured(site.site, {**site.env(), missing: "  "}) is None
        assert configured(site.site, {k: v for k, v in site.env().items() if k != missing}) is None
    assert send_offsite(archive(tmp_path, site, "2026-10-12"), configured(site.site, {}), site.spec) == {
        "offsite": "not set up"}
    said = check_offsite(configured(site.site, {}), site.spec, how_to_set_up=how_to_set_up(site.site))
    p = site.env_prefix
    assert said == {"ok": False, "error": f"not set up: add {p}_B2_BUCKET, {p}_B2_KEY_ID and {p}_B2_APPLICATION_KEY "
                                          "to deploy/.env"}


@each_site
def test_the_settings_are_read_from_the_sites_own_names_and_stripped(site, monkeypatch):
    store = configured(site.site, site.env(bucket=" wts-backups\n", key_id="kid ", application_key=" secret"))
    assert isinstance(store, B2Store) and store.name == "wts-backups" and store._key == ("kid", "secret")
    others = {k: v for other in SITES if other is not site for k, v in other.env().items()}
    assert configured(site.site, others) is None  # another site's settings are not this site's
    for name, value in site.env(bucket="from-the-environment").items():
        monkeypatch.setenv(name, value)
    found = configured(site.site)  # the environment itself, when none is passed
    assert found is not None and found.name == "from-the-environment"


@each_site
def test_upload_retries_and_keeps_the_newest(site, tmp_path):
    fake = FakeB2(fail_uploads=1)
    for day in ("2026-10-10", "2026-10-11", "2026-10-12"):
        out = send(site, fake, archive(tmp_path, site, day), keep=2)
    assert out["ok"] and out["stored"] == 2 and out["deleted"] == 1
    newest = site.archive_name(datetime(2026, 10, 12, tzinfo=UTC))
    assert sorted(fake.files) == [site.archive_name(datetime(2026, 10, 11, tzinfo=UTC)), newest]
    assert json.loads((tmp_path / "offsite.json").read_text()) == out == {
        "ok": True, "when": "2026-10-12T03:31:07+00:00", "file": newest, "bucket": "wts-backups", "stored": 2,
        "deleted": 1}
    assert check_offsite(store_for(site, fake), site.spec) == {"ok": True, "bucket": "wts-backups", "backups": 2,
                                                               "newest": newest}


@each_site
def test_a_key_without_delete_rights_still_stores(site, tmp_path):
    fake = FakeB2(can_delete=False)
    send(site, fake, archive(tmp_path, site, "2026-10-11"), keep=1)
    assert send(site, fake, archive(tmp_path, site, "2026-10-12"), keep=1)["stored"] == 2


@each_site
def test_failures_are_reported_and_recorded(site, tmp_path):
    p = site.env_prefix
    with pytest.raises(OffsiteError, match=f"Backblaze did not accept the key: check {p}_B2_KEY_ID and "
                                           f"{p}_B2_APPLICATION_KEY$"):
        send_offsite(archive(tmp_path, site, "2026-10-12"), store_for(site, FakeB2(), application_key="wrong"),
                     site.spec, clock=FixedClock(WHEN))
    status = json.loads((tmp_path / "offsite.json").read_text())
    assert status["ok"] is False and "wrong" not in json.dumps(status), "the key is never written down"
    with pytest.raises(OffsiteError, match="the key is for the bucket 'someone-else', not 'wts-backups'"):
        send(site, FakeB2(bucket="someone-else"), archive(tmp_path, site, "2026-10-12"))


@each_site
def test_sites_sharing_a_bucket_keep_their_own_backups(site, tmp_path):
    """Another of the charity's sites' backups in the same bucket are neither counted nor deleted."""
    fake = FakeB2()
    others = [other.archive_name(datetime(2026, 10, 1, tzinfo=UTC)) for other in SITES if other is not site]
    for name in others:
        fake.files[name] = b"another site's"
    for day in ("2026-10-11", "2026-10-12"):
        out = send(site, fake, archive(tmp_path, site, day), keep=1)
    assert out["stored"] == 1
    assert sorted(fake.files) == sorted([*others, site.archive_name(datetime(2026, 10, 12, tzinfo=UTC))])
    assert check_offsite(store_for(site, fake), site.spec)["backups"] == 1


# ---- what no site tests ------------------------------------------------------------------------------------------


def test_it_is_an_off_site_store_and_says_what_it_stored(tmp_path):
    site, fake = SITES[1], FakeB2()
    store: OffsiteStore = store_for(site, fake)
    path = archive(tmp_path, site, "2026-10-12")
    assert store.put(path) == StoredFile("wcs-state-2026-10-12.sqlite.gz", "new", len(path.read_bytes()))
    listed = store.list("wcs-state-")
    assert listed == [StoredFile("wcs-state-2026-10-12.sqlite.gz", "id-wcs-state-2026-10-12.sqlite.gz", 17)]
    assert store.list("landlords-") == []
    store.delete(listed[0])
    assert fake.files == {}


def test_an_upload_carries_its_name_its_kind_and_its_sha1_and_one_page_is_listed(tmp_path):
    site, fake = SITES[1], FakeB2()
    path = tmp_path / "wcs-state-2026 10 12.sqlite.gz"  # a name that has to be quoted
    path.write_bytes(b"backup")
    send(site, fake, path)
    [(method, url, headers, body)] = [r for r in fake.requests if r[1].endswith("/upload")]
    assert (method, url, body) == ("POST", "https://up.b2.test/upload", b"backup")
    assert headers == {"authorization": "up", "x-bz-file-name": "wcs-state-2026%2010%2012.sqlite.gz",
                       "content-type": "application/gzip",
                       "x-bz-content-sha1": hashlib.sha1(b"backup").hexdigest()}  # noqa: S324
    listing = [json.loads(r[3]) for r in fake.requests if r[1].endswith("b2_list_file_names")]
    assert listing == [{"bucketId": "b1", "prefix": "wcs-state-", "maxFileCount": 1000}] * 2
    assert fake.requests[0][:2] == ("GET", "https://api.backblazeb2.com/b2api/v2/b2_authorize_account")


def test_the_key_is_offered_when_the_store_is_first_used_and_again_after_it_is_closed(tmp_path):
    site, fake = SITES[2], FakeB2()
    store = store_for(site, fake)
    assert fake.requests == []  # making the store sends nothing: a refused key is then a recorded failure
    store.list("councils-state-")
    store.list("councils-state-")
    assert fake.calls() == ["b2_authorize_account", "b2_list_file_names", "b2_list_file_names"]
    store.close()
    store.close()
    store.put(archive(tmp_path, site, "2026-10-12"))
    assert fake.calls()[3:] == ["b2_authorize_account", "b2_get_upload_url", "upload"]
    send_offsite(archive(tmp_path, site, "2026-10-13"), store, site.spec, keep=1, clock=FixedClock(WHEN))
    assert fake.calls()[6:] == ["b2_get_upload_url", "upload", "b2_list_file_names", "b2_delete_file_version",
                                "b2_list_file_names"]
    check_offsite(store, site.spec)  # send_offsite closed it: the next use starts again
    assert fake.calls()[11:] == ["b2_authorize_account", "b2_list_file_names"]


def test_a_key_not_limited_to_one_bucket_finds_the_bucket_by_name(tmp_path):
    site = SITES[0]
    fake = FakeB2(limited=False, buckets=("other", "wts-backups"))
    assert send(site, fake, archive(tmp_path, site, "2026-10-12"))["stored"] == 1
    assert fake.calls()[:3] == ["b2_authorize_account", "b2_list_buckets", "b2_get_upload_url"]
    assert json.loads(fake.requests[2][3]) == {"bucketId": "id-wts-backups"}
    with pytest.raises(OffsiteError, match="there is no bucket called 'wts-backups' that this key can see"):
        send(site, FakeB2(limited=False, buckets=("other",)), archive(tmp_path, site, "2026-10-12"))
    assert json.loads((tmp_path / "offsite.json").read_text())["ok"] is False


def test_an_upload_refused_three_times_is_a_failure_with_the_last_answer(tmp_path):
    site, fake = SITES[3], FakeB2(fail_uploads=3)
    with pytest.raises(OffsiteError, match="^upload failed: 503 service unavailable$"):
        send(site, fake, archive(tmp_path, site, "2026-10-12"))
    assert fake.calls() == ["b2_authorize_account"] + ["b2_get_upload_url", "upload"] * 3  # a fresh address each time
    assert json.loads((tmp_path / "offsite.json").read_text()) == {
        "ok": False, "when": "2026-10-12T03:31:07+00:00", "error": "upload failed: 503 service unavailable"}
    assert send(site, fake, archive(tmp_path, site, "2026-10-12"))["ok"]


def test_files_are_listed_oldest_first_and_a_long_answer_is_cut_to_two_hundred_characters(tmp_path):
    site, fake = SITES[1], FakeB2()
    answered = [{"fileName": f"wcs-state-{day}.sqlite.gz", "fileId": day} for day in ("2026-10-11", "2026-10-10",
                                                                                      "2026-10-12")]

    def backblaze(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("b2_list_file_names"):  # in an order of its own
            return httpx.Response(200, json={"files": answered})
        if request.url.path == "/upload":
            return httpx.Response(503, text="no " * 100)
        return fake(request)

    store = configured(site.site, site.env(), client=httpx.Client(transport=httpx.MockTransport(backblaze)))
    assert store is not None
    assert [f.id for f in store.list("wcs-state-")] == ["2026-10-10", "2026-10-11", "2026-10-12"]
    with pytest.raises(OffsiteError) as failed:
        store.put(archive(tmp_path, site, "2026-10-13"))
    assert str(failed.value) == "upload failed: 503 " + ("no " * 100)[:200]


def test_a_refused_request_names_the_call_and_the_answer(tmp_path):
    site, fake = SITES[1], FakeB2(can_delete=False)
    store = store_for(site, fake)
    store.put(archive(tmp_path, site, "2026-10-12"))
    with pytest.raises(OffsiteError, match='^b2_delete_file_version: 401 {"code":"unauthorized"}$') as refused:
        store.delete(store.list("wcs-state-")[0])
    assert type(refused.value) is OffsiteError  # refused, not unreachable: the copy just made still counts


@pytest.mark.parametrize("fake, words", [
    (FakeB2(down_at="b2_authorize_account"), "[Errno 101] Network is unreachable"),
    (FakeB2(down_at="upload"), "[Errno 101] Network is unreachable"),
    (FakeB2(down_at="b2_delete_file_version"), "[Errno 101] Network is unreachable"),
    (FakeB2(authorize=500), "Server error '500 Internal Server Error' for url "
                            "'https://api.backblazeb2.com/b2api/v2/b2_authorize_account'"),
], ids=["no network", "lost during the upload", "lost while deleting", "Backblaze in trouble"])
def test_a_bucket_that_cannot_be_reached_is_a_failed_copy_in_httpx_own_words(fake, words, tmp_path):
    site = SITES[1]
    fake.files["wcs-state-2026-10-01.sqlite.gz"] = b"an older copy"
    with pytest.raises(OffsiteError) as failed:
        send(site, fake, archive(tmp_path, site, "2026-10-12"), keep=1)
    assert str(failed.value).startswith(words) and isinstance(failed.value.__cause__, OffsiteUnavailable)
    assert isinstance(failed.value.__cause__.__cause__, httpx.HTTPError)
    status = json.loads((tmp_path / "offsite.json").read_text())
    assert status == {"ok": False, "when": "2026-10-12T03:31:07+00:00", "error": str(failed.value)[:300]}


def test_a_check_with_a_refused_key_or_no_network_is_an_error_for_the_command_to_word():
    """The sites' ``check`` catches nothing, and their ``offsite`` commands end in a traceback; here it is always the
    one kind of error."""
    site = SITES[0]
    with pytest.raises(OffsiteError, match="Backblaze did not accept the key: check HANSARD_B2_KEY_ID"):
        check_offsite(store_for(site, FakeB2(), key_id="someone"), site.spec)
    with pytest.raises(OffsiteUnavailable, match="Network is unreachable"):
        check_offsite(store_for(site, FakeB2(down_at="b2_list_file_names")), site.spec)


def test_a_store_made_without_a_site_says_which_key_was_refused_in_plain_words():
    store = B2Store("wts-backups", "kid", "wrong", FakeB2().client())
    with pytest.raises(OffsiteError, match="^Backblaze did not accept the key: check the key's id and the application "
                                           "key$"):
        store.list("wcs-state-")


def test_a_client_of_its_own_is_made_when_first_needed_and_closed_after(tmp_path, monkeypatch):
    site, fake, made = SITES[1], FakeB2(), []
    ready = [fake.client(), fake.client()]

    def client(**kw: Any) -> httpx.Client:
        made.append((kw, ready.pop(0)))
        return made[-1][1]

    monkeypatch.setattr(httpx, "Client", client)
    store = configured(site.site, site.env())
    assert store is not None and made == []
    assert send_offsite(archive(tmp_path, site, "2026-10-12"), store, site.spec)["stored"] == 1
    [(kw, own)] = made
    assert kw == {"timeout": 300} and own.is_closed
    refused = configured(site.site, site.env(application_key="wrong"))
    assert refused is not None
    with pytest.raises(OffsiteError):
        refused.list("wcs-state-")
    assert len(made) == 2 and made[1][1].is_closed  # closed when the key is refused, too
    monkeypatch.undo()
    given = fake.client()
    store_for_given = configured(site.site, site.env(), client=given)
    assert store_for_given is not None
    store_for_given.list("wcs-state-")
    store_for_given.close()
    assert not given.is_closed  # a client that was passed in is left open


def test_the_adapter_is_imported_without_httpx():
    """httpx is asked for when a store first talks to Backblaze: a site with no off-site copies needn't install it."""
    code = ("import sys; sys.modules['httpx'] = None\n"  # as if it were not installed
            "from pathlib import Path\n"
            "from wts_core.adapters.b2 import configured, how_to_set_up\n"
            "from wts_core.settings import Site\n"
            "site = Site(name='Where Countries Stand', package='wcs', env_prefix='WCS', root=Path('.'))\n"
            "assert configured(site, {}) is None and how_to_set_up(site).startswith('add WCS_B2_BUCKET, ')\n"
            "store = configured(site, {'WCS_B2_BUCKET': 'b', 'WCS_B2_KEY_ID': 'k', 'WCS_B2_APPLICATION_KEY': 'a'})\n"
            "try:\n    store.list('wcs-state-')\nexcept ImportError:\n    print('asked for when first used')\n")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.stdout == "asked for when first used\n", done.stderr


# ---- the same as each site's own code ----------------------------------------------------------------------------


class Theirs:
    """A site's own ``send`` and ``check``, noting what each returned or raised and what ``offsite.json`` then said."""

    def __init__(self, site, folder: Path, fake: FakeB2, own, env: dict[str, str] | None = None) -> None:
        self.site, self.folder, self.fake, self.own = site, folder, fake, own
        self.env = site.env() if env is None else env
        self.log: list[Any] = []
        folder.mkdir()

    def note(self, what: Any) -> None:
        status = self.folder / "offsite.json"
        self.log.append((what, json.loads(status.read_text()) if status.exists() else None))

    def attempt(self, call: Any) -> None:
        try:
            self.note(call())
        except Exception as exc:
            if not isinstance(exc, RuntimeError | httpx.HTTPError):
                raise
            self.note(("raised", str(exc)))

    def send(self, day: str, keep: int = 60) -> None:
        path = archive(self.folder, self.site, day)
        self.attempt(lambda: self.own.offsite.send(path, keep=keep, env=self.env, client=self.fake.client()))

    def check(self) -> None:
        self.attempt(lambda: self.own.offsite.check(env=self.env, client=self.fake.client()))


class Ours(Theirs):
    def store(self) -> B2Store | None:
        return configured(self.site.site, self.env, client=self.fake.client())

    def send(self, day: str, keep: int = 60) -> None:
        path = archive(self.folder, self.site, day)
        self.attempt(lambda: send_offsite(path, self.store(), self.site.spec, keep=keep, clock=FixedClock(WHEN)))

    def check(self) -> None:
        self.attempt(lambda: check_offsite(self.store(), self.site.spec, how_to_set_up=how_to_set_up(self.site.site)))


def three_days_keeping_two(run: Theirs) -> None:
    for day in ("2026-10-10", "2026-10-11", "2026-10-12"):
        run.send(day, keep=2)
    run.check()


def sixty_kept_by_default(run: Theirs) -> None:
    run.send("2026-10-12")
    run.check()


def nothing_there_yet(run: Theirs) -> None:
    run.check()


SCENARIOS: dict[str, tuple[dict[str, Any], dict[str, str] | None, Any]] = {
    "an upload retried": ({"fail_uploads": 1}, None, three_days_keeping_two),
    "no right to delete": ({"can_delete": False}, None, three_days_keeping_two),
    "sixty kept": ({}, None, sixty_kept_by_default),
    "an empty bucket": ({}, None, nothing_there_yet),
    "a wrong key": ({}, {"application_key": "wrong"}, three_days_keeping_two),
    "a key for another bucket": ({"bucket": "someone-else"}, None, three_days_keeping_two),
    "a bucket found by name": ({"limited": False}, None, three_days_keeping_two),
    "no such bucket": ({"limited": False, "buckets": ("other",)}, None, three_days_keeping_two),
    "uploads that keep failing": ({"fail_uploads": 4}, None, three_days_keeping_two),
    "no network": ({"down_at": "b2_authorize_account"}, None, three_days_keeping_two),
    "the network lost during the upload": ({"down_at": "upload"}, None, three_days_keeping_two),
    "the network lost while deleting": ({"down_at": "b2_delete_file_version"}, None, three_days_keeping_two),
    "the network lost while listing": ({"down_at": "b2_list_file_names"}, None, three_days_keeping_two),
    "Backblaze in trouble": ({"authorize": 503}, None, three_days_keeping_two),
    "not set up": ({}, {"bucket": " "}, three_days_keeping_two),
}


@each_site
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_the_package_and_the_sites_own_code_say_and_send_the_same(site, scenario, tmp_path, request, monkeypatch):
    """What each returns or raises, what ``offsite.json`` says after each step, every request sent to Backblaze (its
    address, headers and body) and what is left in the bucket."""
    own = own_code(site, request)
    freeze_their_clock(monkeypatch, own, WHEN)
    backblaze, env, steps = SCENARIOS[scenario]
    runs = []
    for kind in (Theirs, Ours):
        fake = FakeB2(**backblaze)
        for other in SITES:  # the bucket is shared, and has more of this site's copies than are kept
            fake.files[other.archive_name(datetime(2026, 9, 1, tzinfo=UTC))] = b"older"
        for day in range(61):
            fake.files[site.archive_name(datetime(2026, 7, 1, tzinfo=UTC) + timedelta(days=day))] = b"x"
        run = kind(site, tmp_path / kind.__name__, fake, own, None if env is None else site.env(**env))
        steps(run)
        runs.append(run)
    theirs, ours = runs
    assert ours.log == theirs.log
    assert ours.fake.requests == theirs.fake.requests
    assert ours.fake.files == theirs.fake.files
    assert [n for n in theirs.fake.files if not n.startswith(site.spec.prefix)] == [
        o.archive_name(datetime(2026, 9, 1, tzinfo=UTC)) for o in SITES if o is not site]
