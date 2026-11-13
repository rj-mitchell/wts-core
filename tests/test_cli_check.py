"""What answers the nightly family check (ADR 0010): only to the token, and with counts, ages and versions only."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import wts_core
from test_ops_sites import SITES as BACKUP_SITES
from test_ops_sites import each_site
from test_replies_sites import SITES as REPLY_SITES
from test_replies_sites import Open, site_fixture
from wts_core import replies as replies_module
from wts_core import usage
from wts_core.cli import backup_ages, check_route
from wts_core.cli import check as check_module
from wts_core.events import EVENTS_VERSION
from wts_core.ports import Usage
from wts_core.settings import Site
from wts_core.state import StateDB
from wts_core.testing import FixedClock

site = site_fixture()

TOKEN = "f4mily-check-t0ken-3c9a51"
SITE = Site(name="Where Councils Stand", package="councils", env_prefix="COUNCILS", root=Path("."), version="1.4.2")
NOW = FixedClock("2026-11-13T02:10:00+00:00")


# ---- who is answered -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("token", [None, "", "   "])
@pytest.mark.parametrize("presented", [None, "", "Bearer anything", TOKEN])
def test_a_site_with_no_token_set_answers_as_if_the_address_were_not_there(token, presented):
    check = check_route(SITE, token=token, clock=NOW)
    assert check(presented) == (404, {"detail": "Not Found"})


@pytest.mark.parametrize("presented", [None, "", "Bearer", "Bearer ", "Bearer wrong", "wrong", TOKEN[:-1], TOKEN + "x",
                                       f"Basic {TOKEN}", f"Bearer {TOKEN} more", "Bearer ünïcode"])
def test_a_wrong_token_or_none_is_refused_with_nothing_in_the_answer(presented):
    assert check_route(SITE, token=TOKEN, clock=NOW)(presented) == (401, {})


@pytest.mark.parametrize("presented", [f"Bearer {TOKEN}", f"bearer {TOKEN}", f"  Bearer   {TOKEN}  ", TOKEN])
def test_the_token_is_taken_from_the_header_as_sent_or_alone(presented):
    status, body = check_route(SITE, token=f" {TOKEN}\n", clock=NOW)(presented)  # as read from a file of settings
    assert status == 200
    assert body == {"site": "councils", "at": "2026-11-13T02:10:00+00:00",
                    "versions": {"package": wts_core.__version__, "site": "1.4.2", "events": EVENTS_VERSION}}


def test_tokens_are_compared_in_the_same_time_whatever_was_presented(monkeypatch):
    seen: list[tuple[bytes, bytes]] = []
    real = check_module.hmac.compare_digest

    def compare(a: bytes, b: bytes) -> bool:
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(check_module.hmac, "compare_digest", compare)
    check = check_route(SITE, token=TOKEN, clock=NOW)
    assert [check(p)[0] for p in ("Bearer wrong", f"Bearer {TOKEN}", None)] == [401, 200, 401]
    assert seen == [(b"wrong", TOKEN.encode()), (TOKEN.encode(), TOKEN.encode()), (b"", TOKEN.encode())]


def test_nothing_is_read_until_the_token_is_right():
    def never() -> Any:
        raise AssertionError("asked before the token was checked")

    for token, presented in ((None, TOKEN), (TOKEN, "Bearer wrong")):
        check = check_route(SITE, token=token, replies=never, backups=never, figures=never, clock=NOW)
        assert check(presented)[0] in (401, 404)


# ---- what the answer holds -----------------------------------------------------------------------------------------


def test_what_is_waiting_is_counted_and_its_age_is_in_working_days(site):
    check = check_route(SITE, token=TOKEN, replies=site.replies, clock=site.clock)
    assert check(TOKEN)[1]["waiting"] == {"reports": 0, "statements": 0, "hidden": 0, "oldest_working_days": None}
    site.send()  # on a Friday
    site.replies.report(**site.case.report)
    site.replies.hide(site.case.address, "Under review.")
    site.clock.advance(days=6)  # the Thursday after: four working days, when the nightly check starts to fail
    status, body = check(f"Bearer {TOKEN}")
    assert status == 200 and body["waiting"] == {"reports": 1, "statements": 1, "hidden": 1, "oldest_working_days": 4}
    # and a site may give something that returns its Replies, made when it is asked for
    assert check_route(SITE, token=TOKEN, replies=lambda: site.replies, clock=site.clock)(TOKEN)[1]["waiting"] == \
        body["waiting"]


def test_the_figures_and_the_backups_ages_are_passed_on_when_a_site_gives_them():
    check = check_route(SITE, token=TOKEN, clock=NOW,
                        backups=lambda: {"newest_hours": 21.7, "offsite_hours": 21.7, "offsite_ok": True},
                        figures=lambda: {"briefings": 41, "errors": 0, "p95_seconds": 18.4, "by_outcome":
                                         {"completed": 38, "cached": 3}, "useful": None, "daily": [12, 29]})
    _, body = check(TOKEN)
    assert body["backups"] == {"newest_hours": 21.7, "offsite_hours": 21.7, "offsite_ok": True}
    assert body["figures"] == {"briefings": 41, "errors": 0, "p95_seconds": 18.4,
                               "by_outcome": {"completed": 38, "cached": 3}, "useful": None, "daily": [12, 29]}
    assert set(check_route(SITE, token=TOKEN, clock=NOW)(TOKEN)[1]) == {"site", "at", "versions"}


def test_only_numbers_pass_from_what_a_site_gives():
    figures = {"briefings": 41, "commonest_question": "What did the minister say about bins?",
               "themes": {"bins": 3, "What did Cllr Houghton say?": 2, "council tax": 1, "nested": {"who": "A. Reader"}},
               "questions": ["Why?", 3, {"q": "Why?"}], "rate": float("nan"), "ok": False, 7: 1, "x" * 41: 1,
               "p95_seconds": 18.4, "t_first_token": 900, "9f2c4e7a1b3d5f60a1b2c3d4": 4, "a3f9c0d1e2b4a6c8d0e1f2a3": 4}
    _, body = check_route(SITE, token=TOKEN, figures=lambda: figures, backups=lambda: {"newest": "a-file-name.gz"},
                          clock=NOW)(TOKEN)
    assert body["figures"] == {"briefings": 41, "themes": {"bins": 3, "nested": {}}, "questions": [3, {}],
                               "rate": None, "ok": False, "p95_seconds": 18.4, "t_first_token": 900}
    assert body["backups"] == {}
    json.dumps(body, allow_nan=False)  # and it can always be sent


MARKERS = {"question": "zqmark-question What did the minister say about the bins?", "name": "Zqmark-Name Benn",
           "role": "Zqmark-Role for Leeds", "email": "zqmark-email@example.org", "text": "zqmark-text of a statement",
           "message": "zqmark-message of a report", "contact": "zqmark-contact@example.org",
           "note": "zqmark-note shown in its place", "reason": "zqmark-reason it was declined",
           "checked": "zqmark-checked by telephone", "visitor": "zqmark-visitor-code", "address": "203.0.113.77",
           "link": "https://example.org/zqmark-link", "error": "zqmark-error text", "page": "/zqmark-page"}


class Free:
    """Prices for a spending record whose costs do not matter here."""

    def price_for(self, model: str | None) -> Any:
        raise NotImplementedError

    def cost(self, usage: Usage | None, model: str | None) -> float:
        return 0.0


def test_the_check_gives_counts_and_versions_only(site):
    """Every table the package keeps is filled with words that must never leave, and so is what a careless site
    might hand the check: none of them is in the answer, and nothing in the answer is text but the site's name,
    the time and the versions."""
    m = MARKERS
    db = StateDB(site.db.path, migrations=(*replies_module.migrations(), *usage.migrations()), clock=site.clock)
    first = site.send(name=m["name"], role=m["role"], email=m["email"], link=m["link"],
                      text=m["text"] + " in enough words to be accepted by every site.")
    second = site.send(name=m["name"], role=m["role"], email=m["email"], text=m["text"] + " again, in enough words.")
    site.send(email=m["email"])  # one left waiting
    site.replies.publish(first, checked=m["checked"], about="example-housing" if site.key == "landlords" else None)
    site.replies.decline(second, m["reason"])
    site.replies.report(kind=site.case.report["kind"], page=m["page"], message=m["message"], contact=m["contact"],
                        visitor=m["visitor"])
    site.replies.hide(m["page"], m["note"])
    usage.Spending(db, Free(), clock=site.clock).add("answer", "a-model", Usage(), visitor=m["visitor"])
    usage.Failures(db, clock=site.clock).note("answer", m["question"], m["error"])
    usage.SqliteAnswerCache(db, clock=site.clock).put("k", [{"type": "final", "question": m["question"]}], 24)
    with db.connect() as con:
        con.execute("INSERT INTO wts_briefings (id, created_at, question, options, events) VALUES (?, ?, ?, '{}', ?)",
                    ("b1", "2026-11-13T02:00:00+00:00", m["question"], json.dumps([{"text": m["question"]}])))
    db.set("visitor_salt", m["address"])
    code = usage.visitor_code(db, m["address"], clock=site.clock)  # a real one: 24 characters of a hash
    careless = {"asked": 3, "last_question": m["question"], "reporter": m["contact"],
                "by_visitor": {m["visitor"]: 2, code: 5, m["address"]: 1, m["contact"]: 1, "Benn": 1},
                "from": [m["address"]], m["question"]: 1, "statement": {"text": m["text"], "name": m["name"]}}

    check = check_route(SITE, token=TOKEN, replies=site.replies, backups=lambda: careless, figures=lambda: careless,
                        clock=site.clock)
    status, body = check(f"Bearer {TOKEN}")
    assert status == 200 and body["waiting"]["reports"] == 1 and body["waiting"]["statements"] == 1
    sent = json.dumps(body)
    for what, marker in m.items():
        assert marker not in sent and marker.split()[0] not in sent, what
    assert "zqmark" not in sent.lower() and "@" not in sent and code not in sent and "Benn" not in sent

    def texts(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [t for v in value.values() for t in texts(v)]
        if isinstance(value, list):
            return [t for v in value for t in texts(v)]
        return [value] if isinstance(value, str) else []

    assert texts(body) == ["councils", body["at"], wts_core.__version__, "1.4.2"]
    assert body["figures"] == body["backups"] == {"asked": 3, "by_visitor": {}, "from": [], "statement": {}}


# ---- how old the backups are ---------------------------------------------------------------------------------------


@each_site
def test_the_ages_of_the_newest_backup_and_the_last_off_site_copy(site, tmp_path):
    clock = FixedClock("2026-11-13T02:10:00+00:00")
    assert backup_ages(tmp_path / "nowhere", site.spec, clock=clock) == {
        "newest_hours": None, "offsite_hours": None, "offsite_ok": None}
    for days in (3, 1):  # the newest is the last by name
        made = clock.now() - timedelta(days=days, minutes=30)
        archive = tmp_path / site.archive_name(made)
        archive.write_bytes(b"backup")
        os.utime(archive, (made.timestamp(), made.timestamp()))
    other = next(s for s in BACKUP_SITES if s is not site)
    (tmp_path / other.archive_name(clock.now())).write_bytes(b"another site's, in a shared folder")
    assert backup_ages(tmp_path, site.spec, clock=clock) == {
        "newest_hours": 24.5, "offsite_hours": None, "offsite_ok": None}
    (tmp_path / "offsite.json").write_text(json.dumps({"ok": True, "when": "2026-11-12T01:40:00+00:00", "stored": 2}))
    assert backup_ages(tmp_path, site.spec, clock=clock) == {
        "newest_hours": 24.5, "offsite_hours": 24.5, "offsite_ok": True}
    (tmp_path / "offsite.json").write_text(json.dumps({"ok": False, "when": "2026-11-13T01:40:00+00:00",
                                                       "error": "upload failed: 503"}))
    assert backup_ages(tmp_path, site.spec, clock=clock) == {
        "newest_hours": 24.5, "offsite_hours": 0.5, "offsite_ok": False}
    for unreadable in ("not json", "[]", json.dumps({"ok": True}), json.dumps({"ok": True, "when": 7})):
        (tmp_path / "offsite.json").write_text(unreadable)
        assert backup_ages(tmp_path, site.spec, clock=clock)["offsite_hours"] is None, unreadable
    status, body = check_route(SITE, token=TOKEN, backups=lambda: backup_ages(tmp_path, site.spec, clock=clock),
                               clock=clock)(TOKEN)
    assert status == 200 and body["backups"] == {"newest_hours": 24.5, "offsite_hours": None, "offsite_ok": None}


# ---- as a site mounts it -------------------------------------------------------------------------------------------


def a_site(token: str | None, replies: Any = None) -> Any:
    from fastapi import FastAPI, Header
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    app = FastAPI()
    check = check_route(SITE, token=token, replies=replies, clock=NOW)

    # the three lines a site writes
    @app.get("/api/check")
    def api_check(authorization: str | None = Header(None)) -> JSONResponse:
        status, body = check(authorization)
        return JSONResponse(body, status_code=status)

    return TestClient(app)


# the test client's own notice about the library it is built on, which is none of this package's
quietly = pytest.mark.filterwarnings("ignore:Using `httpx` with `starlette.testclient`")


@quietly
def test_mounted_on_a_sites_own_app(tmp_path):
    case = Open(REPLY_SITES["councils"], tmp_path)
    case.replies.report(**case.case.report)
    client = a_site(TOKEN, case.replies)
    assert (client.get("/api/check").status_code, client.get("/api/check").json()) == (401, {})
    wrong = client.get("/api/check", headers={"Authorization": "Bearer wrong"})
    assert (wrong.status_code, wrong.json()) == (401, {})
    right = client.get("/api/check", headers={"Authorization": f"Bearer {TOKEN}"})
    assert right.status_code == 200 and right.json()["waiting"]["reports"] == 1
    assert right.json()["versions"] == {"package": wts_core.__version__, "site": "1.4.2", "events": EVENTS_VERSION}
    assert right.json()["at"] == datetime(2026, 11, 13, 2, 10, tzinfo=UTC).isoformat()


@quietly
def test_a_site_without_the_token_shows_nothing_at_the_address():
    client = a_site(None)
    for headers in ({}, {"Authorization": f"Bearer {TOKEN}"}):
        there, nowhere = client.get("/api/check", headers=headers), client.get("/api/never-was", headers=headers)
        assert (there.status_code, there.json()) == (nowhere.status_code, nowhere.json()) == (
            404, {"detail": "Not Found"})

