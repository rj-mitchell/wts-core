"""Each AI site's own ``ask`` flow, and the briefing desk in its place, for ``test_briefing_parity.py``.

Two sides are built for a site, on the same clock, the same day's visitor secret, the same briefing ids and the same
scripted pipeline:

- ``SiteSide`` is the site's real web app, from its checkout: ``create_app`` in its ``api/app.py``, with its own
  state database in a temporary folder and a scripted pipeline in place of its own (the flow under test begins
  where the pipeline's events arrive). Its package is imported by path, for the test run only, and nothing is
  written into the checkout (no bytecode either).
- ``DeskSide`` is a small web app whose ``/api/ask`` is the route that site would have after adopting the package:
  the site's own request body, key and sources-only search, an ``Ask``, and ``sse(desk.handle(ask))``. What a site
  adds of its own is in its ``Hooks`` here, as it would be in the site.

A scenario is played on one side and then the other, and what was sent and what was written are compared.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import sys
import threading
import types
from collections.abc import Callable, Iterator
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from test_usage_sites import COUNCILS, COUNTRIES, MPS, SiteFacts, checkout_of
from wts_core import usage as core_usage
from wts_core.briefing import Ask, BriefingDesk, Hooks, TooManyRequests, sse
from wts_core.ports import BriefingRecord
from wts_core.state import StateDB
from wts_core.testing import FixedClock
from wts_core.usage import (
    BriefingArchive,
    BriefingsInProgress,
    Caps,
    Failures,
    Limits,
    PriceTable,
    RateLimiter,
    Spending,
    SqliteAnswerCache,
    cache_key,
    visitor_code,
)

START = "2026-11-13T12:00:00+00:00"
SALT = "5a" * 16
HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
DONATE = "https://example.org/support"


# ---- loading a site's own code ---------------------------------------------------------------------------------


def _stand_in_for_argon2() -> None:
    """Where MPs Stand's sign-in hashes passwords with argon2, which the package's test environment does not have.
    Nothing on the path being compared hashes a password, so where the library is missing a stand-in with the same
    three methods is put in its place for the test run."""
    try:
        import argon2  # noqa: F401
        return
    except ImportError:
        pass
    exceptions = types.ModuleType("argon2.exceptions")

    class VerificationError(Exception):
        pass

    class InvalidHashError(Exception):
        pass

    class PasswordHasher:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def hash(self, password: str) -> str:
            return "stand-in$" + password

        def verify(self, hashed: str, password: str) -> bool:
            if hashed != "stand-in$" + password:
                raise VerificationError
            return True

        def check_needs_rehash(self, hashed: str) -> bool:
            return False

    exceptions.VerificationError = VerificationError  # type: ignore[attr-defined]
    exceptions.VerifyMismatchError = VerificationError  # type: ignore[attr-defined]
    exceptions.InvalidHashError = InvalidHashError  # type: ignore[attr-defined]
    module = types.ModuleType("argon2")
    module.PasswordHasher = PasswordHasher  # type: ignore[attr-defined]
    module.exceptions = exceptions  # type: ignore[attr-defined]
    sys.modules["argon2"], sys.modules["argon2.exceptions"] = module, exceptions


_LOADED: dict[str, SimpleNamespace] = {}


def site_code(facts: SiteFacts) -> SimpleNamespace:
    """The site's own modules, imported from its checkout: ``app``, ``usage``, ``state`` (the module its state
    database is in), ``config`` and ``query_parse``. The test is skipped, saying why, when the checkout is absent or
    a library the site's web app imports is not installed."""
    checkout_of(facts)
    pytest.importorskip("fastapi", reason="the sites' web apps need FastAPI (the dev group has it)")
    if facts.package in _LOADED:
        return _LOADED[facts.package]
    src = str(facts.checkout / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    if facts is MPS:
        _stand_in_for_argon2()
    pkg = facts.package
    state_name = {"hansard": "hansard.store.state", "wcs": "wcs.api.usage", "councils": "councils.api.state"}[pkg]
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # leave nothing in the site's checkout
    try:
        mods = SimpleNamespace(
            app=importlib.import_module(f"{pkg}.api.app"), usage=importlib.import_module(f"{pkg}.api.usage"),
            state=importlib.import_module(state_name), config=importlib.import_module(f"{pkg}.config"),
            query_parse=importlib.import_module(f"{pkg}.rag.query_parse"),
            pipeline=importlib.import_module(f"{pkg}.rag.pipeline"))
        if facts is MPS:
            mods.briefings = importlib.import_module("hansard.api.briefings")
            mods.auth = importlib.import_module("hansard.api.auth")
    except ImportError as exc:
        pytest.skip(f"{facts.name}'s web app cannot be imported here: {exc}. Its own flow needs the libraries the "
                    "site uses (run `uv sync --all-extras`)")
    finally:
        sys.dont_write_bytecode = writes
    _LOADED[pkg] = mods
    return mods


def frozen(clock: FixedClock) -> type[datetime]:
    """``datetime`` for a site's module, with the test's clock for ``now``."""

    class SiteDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return clock.now()

    return SiteDatetime


def fix_the_sites_clock(mods: SimpleNamespace, clock: FixedClock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every time the site's usage code and state database read is the test's."""
    for module in {mods.usage, mods.state}:
        if hasattr(module, "datetime"):
            monkeypatch.setattr(module, "datetime", frozen(clock))


# ---- a scripted pipeline, in each site's own shapes --------------------------------------------------------------

PARSE_USAGE = {"input_tokens": 1200, "output_tokens": 80, "cache_read_tokens": 0, "cache_write_tokens": 0}
ANSWER_USAGE = {"input_tokens": 9000, "output_tokens": 700, "cache_read_tokens": 3000, "cache_write_tokens": 2000}
INTERESTS_USAGE = {"input_tokens": 400, "output_tokens": 30, "cache_read_tokens": 0, "cache_write_tokens": 0}
DECLINED = "The model declined to answer this question."
NO_KEY_NOTE = {"hansard": "Showing the evidence set only (no Anthropic API key on the server).",
               "wcs": "Showing the evidence only (no Anthropic API key set).",
               "councils": "Showing the evidence only (no Anthropic API key set)."}
CARDS = [
    {"n": 1, "title": "Security Council, 9000th meeting", "group": "KEN", "voted_on": date(2024, 12, 17)},
    {"n": 2, "title": "General Assembly, 79th session", "group": "FJI"},
    {"n": 3, "title": "Security Council, 9001st meeting", "group": "KEN"},
]


def an_answer() -> dict[str, Any]:
    """A checked briefing as every site's verifier reports one: a cited sentence with a quotation, a sentence
    marked for checking that today's rules clear when it is replayed (it only leads in to the citation after it),
    one that stays marked, and a judgemental-word mark that no site's list holds any more."""
    segments = [
        {"text": "Kenya said that climate finance was \"too slow\".", "sources": [1],
         "cited": [{"n": 1, "text": "climate finance for adaptation is too slow"}], "status": "cited", "loaded": [],
         "misquotes": []},
        {"text": " In the debate that followed:", "sources": [], "cited": [], "status": "unsupported", "loaded": [],
         "misquotes": []},
        {"text": " Fiji warned that finance must reach small islands.", "sources": [2],
         "cited": [{"n": 2, "text": "climate finance must reach small islands"}], "status": "cited", "loaded": [],
         "misquotes": []},
        {"text": " This was a turning point for every delegation in the room.", "sources": [], "cited": [],
         "status": "unsupported", "loaded": [{"start": 12, "end": 19, "word": "turning"}], "misquotes": []},
    ]
    markdown = "".join(s["text"] for s in segments)
    return {"segments": segments, "markdown": markdown, "no_records": False, "citations_total": 2,
            "citations_invalid": 0, "grounded_ratio": 0.5, "unsupported_segments": 2, "loaded_words": 1,
            "quotes_total": 1, "quotes_unverified": 0}


def no_records_answer(package: str) -> dict[str, Any]:
    where = "minutes contain" if package == "councils" else "archive contains"
    answer = {"segments": [{"text": f"No records found. The {where} no records matching this question and these "
                                    "filters.", "sources": [], "cited": [], "status": "connective"}],
              "markdown": "No records found.", "no_records": True, "citations_total": 0, "citations_invalid": 0,
              "grounded_ratio": 1.0}
    if package == "hansard":
        answer["unsupported_segments"] = 0
    return answer


class FakePlan:
    """What a site's ``QueryPlan`` gives its route: the question, whether the model failed to read it, and itself
    as a dictionary. ``parser`` says who read the question, so the bytes sent show it."""

    def __init__(self, question: str, parser: str, parse_error: str | None = None) -> None:
        self.question, self.parser, self.parse_error = question, parser, parse_error
        self.group_by = None

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "parser": self.parser, "filters": {"date_from": "2020-01-01"}}


class FakeSource:
    def __init__(self, card: dict[str, Any]) -> None:
        self._card, self.kind = card, "record"

    def card(self) -> dict[str, Any]:
        return dict(self._card)


class ScriptedPipeline:
    """In place of a site's ``Pipeline``: ``run`` sends the events of the next behaviour in ``plays`` (or of
    ``"written"``), in the site's own shapes, moving the clock as a real one takes time. ``make_plan`` and ``find``
    are what the site's sources-only search asks of it."""

    def __init__(self, package: str, clock: FixedClock, model: str, *, has_model: bool = True) -> None:
        self.package, self.clock, self.model, self.model_on = package, clock, model, has_model
        self.today = date(2026, 11, 13)
        self.engine = SimpleNamespace(countries=None)
        self.plays: list[str] = []
        self.calls: list[str] = []  # the behaviours run, and "make_plan" for each question the model read alone
        self.entered, self.gate, self.closed = threading.Event(), threading.Event(), threading.Event()

    def has_model(self) -> bool:
        return self.model_on

    # what the sites' routes ask besides run()

    def make_plan(self, req: Any) -> tuple[FakePlan, dict[str, int] | None]:
        self.calls.append("make_plan")
        if not self.model_on:
            return FakePlan(req.question, "offline"), None
        return FakePlan(req.question, "model"), dict(PARSE_USAGE)

    def find(self, plan: Any, req: Any) -> tuple[Any, ...]:
        result = SimpleNamespace(candidates=12, semantic_available=True, evidence={"records": 3}, timings={})
        sources = [FakeSource(c) for c in CARDS]
        if self.package == "councils":
            return result, sources
        return result, ["a vote"], sources

    def group_aliases(self) -> dict[str, Any]:
        return {}

    def _set_comparison(self, plan: Any, req: Any) -> None:
        pass

    # the events of a briefing

    def _plan(self, question: str, **more: Any) -> dict[str, Any]:
        usage = dict(PARSE_USAGE) if self.model_on else None
        return {"type": "plan", "plan": FakePlan(question, "model" if self.model_on else "offline").to_dict(),
                "usage": usage, **more}

    def _sources(self) -> dict[str, Any]:
        return {"type": "sources", "sources": [dict(c) for c in CARDS], "candidates": 12, "semantic": True,
                "evidence": {"records": 3, "votes": 1}}

    def _final(self) -> dict[str, Any]:
        final = {"type": "final", "answer": an_answer(), "usage": dict(ANSWER_USAGE), "model": self.model,
                 "stop_reason": "end_turn"}
        if self.package == "hansard":
            final["interests"] = [{"member": "A Member", "interest": "A directorship", "public_office": False}]
            final["interests_usage"] = dict(INTERESTS_USAGE)
        return final

    def run(self, req: Any) -> Iterator[dict[str, Any]]:
        play = self.plays.pop(0) if self.plays else "written"
        self.calls.append(play)
        mps, tick = self.package == "hansard", self.clock.advance
        question = req.question
        if mps:
            yield {"type": "progress", "step": "reading", "passages": 123456}
        tick(0.4)
        yield self._plan(question, **({"parse_error": "AuthenticationError: bad key"} if play == "unread" else {}))
        tick(0.3)
        yield self._sources()
        if play == "no_records":
            yield {"type": "final", "answer": no_records_answer(self.package), "usage": None}
            return
        if not self.model_on:
            yield {"type": "final", "answer": None, "usage": None, "note": NO_KEY_NOTE[self.package]}
            return
        if play == "held":  # a briefing still being written while another question arrives
            self.entered.set()
            assert self.gate.wait(20)
        tick(1.5)
        # as the model really sends them: a citation comes before the text of the block it belongs to
        yield {"type": "citation", "search_result_index": 0, "cited_text": "climate finance for adaptation is too slow"}
        yield {"type": "text", "text": "Kenya said that climate finance "}
        if play == "raises":
            raise RuntimeError("the model's stream broke")
        if play == "left":  # the reader goes while the briefing is being written
            try:
                self.entered.set()
                assert self.gate.wait(20)
                for word in ("was ", "\"too ", "slow\"."):
                    tick(0.1)
                    yield {"type": "text", "text": word}
            finally:
                self.closed.set()
            raise AssertionError("the pipeline was not stopped when the reader left")
        yield {"type": "text", "text": "was \"too slow\"."}
        yield {"type": "citation", "search_result_index": 1, "cited_text": "climate finance must reach small islands"}
        yield {"type": "text", "text": " Fiji warned that finance must reach small islands."}
        if mps:
            yield {"type": "interests", "interests": [{"member": "A Member", "interest": "A directorship"}]}
        tick(2.0)
        if play == "declined":
            if mps:
                yield {"type": "error", "message": DECLINED}
            else:  # the call was still paid for, so its token counts go with the event to be recorded
                yield {"type": "error", "message": DECLINED, "usage": dict(ANSWER_USAGE), "model": self.model}
            return
        if mps:
            yield {"type": "progress", "step": "checking"}
        tick(0.6)
        yield self._final()


# ---- the two sides ----------------------------------------------------------------------------------------------


class Side:
    """What a scenario may do, on either side."""

    facts: SiteFacts
    pipeline: ScriptedPipeline
    clock: FixedClock
    app: Any
    client: Any

    def ask(self, question: str, play: str = "written", **body: Any) -> tuple[int, bytes]:
        """One question through ``/api/ask``: the status and the exact bytes of the answer."""
        if play != "written":
            self.pipeline.plays.append(play)
        response = self.client.post("/api/ask", json={"question": question, **body})
        return response.status_code, response.content

    def another_client(self) -> Any:
        from fastapi.testclient import TestClient

        client = TestClient(self.app)
        client.cookies.update(self.client.cookies)
        return client

    def stream(self, question: str, **body: Any) -> Iterator[bytes]:
        """The answer as the web server would take it, piece by piece, so that it can be closed part-way."""
        raise NotImplementedError

    def rows(self) -> dict[str, list[tuple[Any, ...]]]:
        raise NotImplementedError

    def briefings_today(self, visitor: str) -> int:
        raise NotImplementedError

    def sign_in(self) -> None:
        raise NotImplementedError

    def edit_cache(self, change: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]) -> None:
        """Rewrite every cached answer's events: for an answer cached by an older version of the site."""
        raise NotImplementedError


REQUEST = SimpleNamespace(client=SimpleNamespace(host="testclient"), headers={}, cookies={})


def site_settings(facts: SiteFacts, mods: SimpleNamespace, folder: Path, usage: dict[str, Any]) -> Any:
    """The site's real settings, with its data in a temporary folder and the scenario's limits."""
    s = mods.config.load_settings()
    raw = {**s.raw, "usage": {**s.raw["usage"], **usage}}
    if facts is MPS:
        raw["auth"] = {"required": False}
        raw["site"] = {**raw.get("site", {}), "donate_url": DONATE}
    folder.mkdir(parents=True, exist_ok=True)
    return dataclasses.replace(s, raw=raw, data_dir=folder)


def offline_reader(question: str, *args: Any, **kwargs: Any) -> FakePlan:
    """In place of each site's ``parse_offline``, which needs its reference data: the built-in rules read it."""
    return FakePlan(question, "offline")


class SiteSide(Side):
    """The site's own ``create_app``, with its clock, the day's visitor secret and its briefing ids fixed."""

    def __init__(self, facts: SiteFacts, folder: Path, clock: FixedClock, monkeypatch: pytest.MonkeyPatch, *,
                 has_model: bool = True, **usage: Any) -> None:
        from fastapi.testclient import TestClient

        mods = site_code(facts)
        self.facts, self.mods, self.clock = facts, mods, clock
        fix_the_sites_clock(mods, clock, monkeypatch)
        monkeypatch.setattr(mods.app if facts is COUNCILS else mods.query_parse, "parse_offline", offline_reader)
        ids = (f"briefing{n:03d}" for n in range(1, 100))
        if facts is MPS:
            monkeypatch.setattr(mods.briefings, "new_id", lambda: next(ids))
        elif facts is COUNTRIES:
            monkeypatch.setattr(mods.app, "new_briefing_id", lambda: next(ids))
        else:
            monkeypatch.setattr(mods.state.StateDB, "new_briefing_id", staticmethod(lambda: next(ids)))
        self.settings = site_settings(facts, mods, folder / "site", usage)
        self.state = mods.state.StateDB(folder / "site" / ("state.sqlite" if facts is MPS else "state.db"))
        with self.state.connect() as con:
            con.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (f"visitor_salt:{START[:10]}", SALT))
        self.pipeline = ScriptedPipeline(facts.package, clock, self.settings.answer["model"], has_model=has_model)
        self.app = mods.app.create_app(self.settings, pipeline=self.pipeline, state=self.state)
        self.client = TestClient(self.app)
        self._monkeypatch = monkeypatch
        self._signed_in = False

    def sign_in(self) -> None:
        self.mods.auth.create_user(self.state, "researcher@example.org", "correct horse battery")
        response = self.client.post("/api/auth/login", json={"email": "researcher@example.org",
                                                             "password": "correct horse battery"})
        assert response.status_code == 200, response.text
        self._signed_in = True

    def stream(self, question: str, **body: Any) -> Iterator[bytes]:
        # the route's own function, with the response it builds left as the bytes it would send
        route = next(r.endpoint for r in self.app.routes if getattr(r, "path", "") == "/api/ask")
        asked = self.mods.app.AskBody(question=question, **body)
        with self._monkeypatch.context() as patch:
            patch.setattr(self.mods.app, "StreamingResponse", lambda content, **kwargs: content)
            out = route(asked, REQUEST, user=None) if self.facts is MPS else route(asked, REQUEST)
        return out  # type: ignore[no-any-return]

    def edit_cache(self, change: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]) -> None:
        with self.state.connect() as con:
            for key, events in con.execute("SELECT key, events FROM answer_cache").fetchall():
                con.execute("UPDATE answer_cache SET events = ? WHERE key = ?",
                            (json.dumps(change(json.loads(events)), default=str), key))

    def rows(self) -> dict[str, list[tuple[Any, ...]]]:
        f = self.facts
        account = "user_id" if f is MPS else "NULL"
        cached_at = "at" if f is COUNCILS else "created_at"
        saved = ("id, created_at, question, settings, events, records_up_to, model" if f is MPS
                 else "id, at, question, options, events")
        with self.state.connect() as con:
            briefings = [tuple(r) for r in con.execute(f"SELECT {saved} FROM briefings ORDER BY id")]
            return {
                "spending": [tuple(r) for r in con.execute(
                    f"SELECT at, kind, model, visitor, {account}, input_tokens, output_tokens, cache_read_tokens, "
                    f"cache_write_tokens, cost_usd FROM usage ORDER BY {'rowid' if f is COUNCILS else 'id'}")],
                "cache": [tuple(r) for r in con.execute(
                    f"SELECT key, {cached_at}, events FROM answer_cache ORDER BY key")],
                "briefings": [(*b[:5], {"records_up_to": b[5], "model": b[6]} if f is MPS else {})
                              for b in briefings],
                "failures": [] if f is COUNCILS else [tuple(r) for r in con.execute(
                    "SELECT at, kind, question, error FROM failures ORDER BY id")],
            }

    def briefings_today(self, visitor: str) -> int:
        u = self.mods.usage
        if self.facts is COUNCILS:
            return int(u.questions_today(self.state, visitor))
        with self.state.connect() as con:
            return int(con.execute("SELECT count(*) FROM usage WHERE visitor = ? AND kind = 'answer' AND at >= ?",
                                   (visitor, START[:10])).fetchone()[0])


class ListLog:
    """A briefing log that keeps its records in a list (``ports.BriefingLog``)."""

    def __init__(self) -> None:
        self.records: list[BriefingRecord] = []

    def write(self, record: BriefingRecord) -> None:
        self.records.append(record)

    def mark(self, briefing_id: str, *, useful: bool | None = None, reported: bool = False, corrected: bool = False,
             followed_up: bool = False) -> None:
        raise NotImplementedError


class DeskSide(Side):
    """The same site with the briefing desk in place of its own flow: the ``wts_`` tables, the site's messages and
    limits, and a route written as the site's would be after adopting the package."""

    def __init__(self, facts: SiteFacts, folder: Path, clock: FixedClock, monkeypatch: pytest.MonkeyPatch, *,
                 has_model: bool = True, **usage: Any) -> None:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import StreamingResponse
        from fastapi.testclient import TestClient

        mods = site_code(facts)
        self.facts, self.mods, self.clock = facts, mods, clock
        fix_the_sites_clock(mods, clock, monkeypatch)  # for the site's own counting, where a route still uses it
        monkeypatch.setattr(mods.app if facts is COUNCILS else mods.query_parse, "parse_offline", offline_reader)
        self.settings = settings = site_settings(facts, mods, folder / "desk", usage)
        cfg = settings.usage
        self.db = db = StateDB(folder / "desk" / "wts.db", migrations=core_usage.migrations(), clock=clock)
        db.set(f"visitor_salt:{START[:10]}", SALT)
        ids = (f"briefing{n:03d}" for n in range(1, 100))
        self.spending = Spending(db, PriceTable.from_settings(cfg), clock=clock)
        self.cache = SqliteAnswerCache(db, clock=clock)
        self.archive = BriefingArchive(db, new_id=lambda: next(ids), clock=clock)
        self.failures = None if facts is COUNCILS else Failures(db, clock=clock)  # Councils only logs a failure
        self.caps = Caps(self.spending, Limits.from_settings(cfg), facts.messages, clock)
        self.cache_hours = float(cfg.get("answer_cache_hours", 168))
        self.log = ListLog()
        self.pipeline = ScriptedPipeline(facts.package, clock, settings.answer["model"], has_model=has_model)
        self.account: int | None = None
        route, hooks = ROUTES[facts.package](self)
        self.desk = BriefingDesk(
            messages=facts.messages,
            limiter=RateLimiter(int(cfg.get("requests_per_minute", 20)), forget_over=facts.forget_over, clock=clock),
            caps=self.caps,
            in_progress=BriefingsInProgress(int(cfg.get(facts.at_once_key, 2)), int(cfg.get("briefings_at_once", 8)),
                                            float(cfg["briefing_estimate_usd"])),
            spending=self.spending, cache=self.cache, cache_hours=self.cache_hours, archive=self.archive,
            failures=self.failures, log=self.log, parse_model=mods.query_parse.parse_model(settings),
            config={"config_id": "0123456789ab", "model": settings.answer["model"], "site_version": "test"},
            hooks=hooks, group_of=lambda card: card.get("group"), clock=clock, strict=True)
        self._route = route
        self.app = FastAPI()

        def limited(key: str) -> None:
            try:
                self.desk.allow(key)
            except TooManyRequests as exc:
                raise HTTPException(429, exc.message) from None

        self.limited = limited

        def ask(body: Any, request: Any) -> Any:
            return StreamingResponse(route(body, request), media_type="text/event-stream", headers=HEADERS)

        # the site's own request body: given as objects, since this file's annotations are kept as text
        ask.__annotations__ = {"body": mods.app.AskBody, "request": Request}
        self.app.post("/api/ask")(ask)
        self.client = TestClient(self.app)

    def visitor(self, request: Any) -> str:
        return visitor_code(self.db, request.client.host if request.client else None, clock=self.clock)

    def sign_in(self) -> None:
        self.account = 1  # the first account made: as the site's own sign-in gives it

    def stream(self, question: str, **body: Any) -> Iterator[bytes]:
        return self._route(self.mods.app.AskBody(question=question, **body), REQUEST)  # type: ignore[no-any-return]

    def rows(self) -> dict[str, list[tuple[Any, ...]]]:
        with self.db.connect() as con:
            return {
                "spending": [tuple(r) for r in con.execute(
                    "SELECT at, kind, model, visitor, account, input_tokens, output_tokens, cache_read_tokens, "
                    "cache_write_tokens, cost_usd FROM wts_spending ORDER BY id")],
                "cache": [tuple(r) for r in con.execute(
                    "SELECT key, created_at, events FROM wts_answer_cache ORDER BY key")],
                "briefings": [(*tuple(r)[:5], json.loads(r["extra"])) for r in con.execute(
                    "SELECT id, created_at, question, options, events, extra FROM wts_briefings ORDER BY id")],
                "failures": [tuple(r) for r in con.execute(
                    "SELECT at, kind, question, error FROM wts_failures ORDER BY id")],
            }

    def briefings_today(self, visitor: str) -> int:
        return self.spending.briefings_today(visitor=visitor)

    def edit_cache(self, change: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]) -> None:
        with self.db.connect() as con:
            for key, events in con.execute("SELECT key, events FROM wts_answer_cache").fetchall():
                con.execute("UPDATE wts_answer_cache SET events = ? WHERE key = ?",
                            (json.dumps(change(json.loads(events)), default=str), key))


# ---- each site's route, as it would be after adopting the package -----------------------------------------------

type Route = Callable[[Any, Any], Iterator[bytes]]


def plain_question(question: str) -> str:
    return " ".join(question.lower().split())


def countries_route(side: DeskSide) -> tuple[Route, Hooks]:
    app, settings, p = side.mods.app, side.settings, side.pipeline
    from wcs.rag.pipeline import AskRequest
    from wcs.rag.query_parse import QueryPlan

    class CountriesHooks(Hooks):
        def on_cached(self, ask: Ask, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return app.rechecked(events)  # type: ignore[no-any-return]

    def request_for(body: Any) -> Any:
        return AskRequest(question=body.question, mode=body.mode, plan=body.plan, recency=body.recency,
                          role_weight=body.role_weight, history=[t.model_dump() for t in body.history])

    def sources_only(body: Any, note: str) -> Iterator[dict[str, Any]]:
        req = request_for(body)
        if body.plan:
            plan = QueryPlan.from_dict({"question": body.question, **body.plan})
        else:
            from wcs.rag import query_parse

            plan = query_parse.parse_offline(body.question, p.engine.countries, p.today or date.today(),
                                             int(settings.archive.get("default_years", 10)), settings.start_date)
        result, votes, sources = p.find(plan, req)
        yield {"type": "plan", "plan": plan.to_dict(), "usage": None}
        yield {"type": "sources", "sources": [s.card() for s in sources], "candidates": result.candidates,
               "semantic": result.semantic_available, "evidence": {**result.evidence, "votes": len(votes)}}
        yield {"type": "final", "answer": None, "usage": None, "note": note}

    def route(body: Any, request: Any) -> Iterator[bytes]:
        who = side.visitor(request)
        side.limited(who)
        model_on = p.has_model()
        key = None
        if model_on and side.cache_hours > 0 and not body.history:  # a follow-up is never cached
            key = cache_key({"q": plain_question(body.question), **body.model_dump(exclude={"question"}),
                             "model": settings.answer.get("model"), "data": app.data_stamp(settings),
                             "instructions": app.INSTRUCTIONS_VERSION})
        return sse(side.desk.handle(Ask(
            question=body.question, visitor=who, write=lambda: p.run(request_for(body)),
            sources_only=lambda note, free: sources_only(body, note),  # always the built-in rules, free
            cache_key=key, only_sources=body.sources_only, model_available=model_on, follow_up=bool(body.history),
            mode=body.mode, options=body.model_dump(exclude={"question", "history"}))))

    return route, CountriesHooks()


def councils_route(side: DeskSide) -> tuple[Route, Hooks]:
    app, settings, p = side.mods.app, side.settings, side.pipeline
    from councils.api.data import Data
    from councils.rag.pipeline import AskRequest
    from councils.rag.query_parse import QueryPlan, parse_model

    data = Data(settings)

    class CouncilsHooks(Hooks):
        def on_cached(self, ask: Ask, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return app.rechecked(events)  # type: ignore[no-any-return]

        def on_event(self, ask: Ask, event: dict[str, Any]) -> dict[str, Any] | None:
            # token counts are for the spending record: this site sends none to the reader
            return {k: v for k, v in event.items() if k != "usage"} if event["type"] in ("plan", "final") else event

    def offline_plan(body: Any) -> Any:
        if body.plan:
            return QueryPlan.from_dict({"question": body.question, **body.plan})
        return app.parse_offline(body.question, date.today(), int(settings.archive.get("default_years", 4)),
                                 settings.start_date)

    def route(body: Any, request: Any) -> Iterator[bytes]:
        v = side.visitor(request)
        side.limited(v)
        req = AskRequest(question=body.question, mode=body.mode, plan=body.plan, history=body.history_dicts())
        key = cache_key({"q": plain_question(body.question), **body.model_dump(exclude={"question"}),
                         "data": data.stamp(), "model": settings.answer.get("model"), "v": app.INSTRUCTIONS_VERSION},
                        length=32)

        def sources_only(note: str, free: bool) -> Iterator[dict[str, Any]]:
            if free:  # over a limit, or the site's spending cap is reached: the question is read by the free rules
                plan = offline_plan(body)
            else:  # the model reads the question better, for a fraction of a penny
                plan, used = p.make_plan(req)
                side.spending.add("parse", parse_model(settings), used, visitor=v)
            result, sources = p.find(plan, req)
            yield {"type": "plan", "plan": plan.to_dict(), "usage": None}
            yield {"type": "sources", "sources": [s.card() for s in sources], "candidates": result.candidates,
                   "semantic": result.semantic_available, "evidence": result.evidence}
            yield {"type": "final", "answer": None, "usage": None, "note": note}

        return sse(side.desk.handle(Ask(
            question=body.question, visitor=v, write=lambda: p.run(req), sources_only=sources_only, cache_key=key,
            only_sources=body.sources_only, model_available=p.has_model(), follow_up=bool(body.history),
            mode=body.mode, options=body.model_dump(exclude={"question", "history"}))))

    return route, CouncilsHooks()


def mps_route(side: DeskSide) -> tuple[Route, Hooks]:
    app, usage, settings, p = side.mods.app, side.mods.usage, side.settings, side.pipeline
    from hansard.devolution import notes_for
    from hansard.engine import Scope
    from hansard.rag.interests import without_public_office
    from hansard.rag.pipeline import AskRequest
    from hansard.rag.query_parse import QueryPlan, parse_model

    # the site's own database stays, for what is the site's own: its update runs, its records, its daily counts
    state = side.mods.state.StateDB(settings.data_dir / "state.sqlite")
    every = int(settings.usage.get("support_reminder_every", 10))

    def keep(ask: Ask, kept: list[dict[str, Any]], final: dict[str, Any]) -> dict[str, Any]:
        """Keep a just-written briefing from its stream events; its id, preparation time and record date."""
        records_up_to = state.latest_record_date()
        events = [e for e in kept if e["type"] in ("plan", "sources")] + [
            {k: v for k, v in final.items() if k not in ("usage", "briefing_key", "support_reminder")}]
        saved = side.archive.save(ask.question, ask.options, events,
                                  extra={"records_up_to": records_up_to, "model": final.get("model")})
        return {"briefing_id": saved.id, "prepared_at": saved.created_at, "records_up_to": records_up_to}

    class MpsHooks(Hooks):
        def on_cached(self, ask: Ask, hit: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if hit and hit[-1].get("interests"):  # saved before posts in government were left out
                hit[-1] = {**hit[-1], "interests": without_public_office(hit[-1]["interests"])}
            final = hit[-1]
            if final.get("answer") and not final["answer"].get("no_records") and not final.get("briefing_id"):
                # cached before shareable links existed: give it an address now, and remember it
                assert ask.cache_key is not None
                hit[-1] = {**final, **keep(ask, hit, final)}
                side.cache.put(ask.cache_key, hit, side.cache_hours)
            return hit

        def usages(self, ask: Ask, event: dict[str, Any]) -> list[tuple[str, str | None, Any]]:
            if event["type"] == "final" and event.get("interests_usage"):
                return [("interests", parse_model(settings), event["interests_usage"])]
            return []

        def on_event(self, ask: Ask, event: dict[str, Any]) -> dict[str, Any] | None:
            if event["type"] == "final":
                return {k: v for k, v in event.items() if k != "interests_usage"}
            return event

        def finish(self, ask: Ask, final: dict[str, Any], kept: list[dict[str, Any]]) -> dict[str, Any]:
            # lets the reader's feedback refer to this briefing
            return {**final, "briefing_key": ask.cache_key} if ask.cache_key else final

        def for_this_reader(self, ask: Ask, final: dict[str, Any]) -> dict[str, Any]:
            # the note on costs, after every so many new briefings a visitor has had written today
            if not final.get("usage") or ask.account is not None or not app.donate_url(settings) or not ask.visitor:
                return final
            n = side.spending.briefings_today(visitor=ask.visitor)
            due = n > 0 and every > 0 and n % every == 0 and state.get(usage._supporter_key(ask.visitor)) is None
            return {**final, "support_reminder": n} if due else final

    def retrieve(body: Any, read_with_model: bool, uid: int | None, visitor: str | None) -> dict[str, Any]:
        if body.plan:
            plan = QueryPlan.from_dict({"question": body.question, **body.plan})
        elif read_with_model and p.has_model():
            plan, used = p.make_plan(AskRequest(question=body.question, history=body.history_dicts(),
                                                compare=body.compare))
            if plan.parse_error:
                side.failures.note("question reading", body.question, plan.parse_error)  # type: ignore[union-attr]
            if used:
                side.spending.add("parse", parse_model(settings), used, visitor=visitor, account=uid)
        else:
            from hansard.rag import query_parse

            plan = query_parse.parse_offline(body.question, settings.regions, p.today, p.group_aliases())
            p._set_comparison(plan, AskRequest(question=body.question, compare=body.compare))
        req = AskRequest(question=body.question, mode=body.mode, recency=body.recency, role_weight=body.role_weight,
                         scope=Scope(**body.scope.model_dump()))
        res, _, sources = p.find(plan, req)
        shown = [s.card() for s in sources if s.kind in ("record", "edm", "devolved", "evidence")]
        return {"plan": plan.to_dict(), "sources": shown, "candidates": res.candidates,
                "semantic": res.semantic_available,
                "evidence": {**res.evidence, "devolution": notes_for(plan.question),
                             "edms": sum(1 for s in sources if s.kind == "edm"),
                             "devolved": sum(1 for s in sources if s.kind == "devolved"),
                             "committee_evidence": sum(1 for s in sources if s.kind == "evidence")}
                if res.evidence else res.evidence}

    def sources_only(body: Any, note: str, uid: int | None, visitor: str | None) -> Iterator[dict[str, Any]]:
        # read the question with the model unless the site's own budget is used up, whatever stopped this reader
        r = retrieve(body, side.caps.site_paused() is None, uid, visitor)
        yield {"type": "plan", "plan": r["plan"], "usage": None}
        yield {"type": "sources", **{k: r[k] for k in ("sources", "candidates", "semantic", "evidence")}}
        yield {"type": "final", "answer": None, "usage": None, "note": note}

    def route(body: Any, request: Any) -> Iterator[bytes]:
        uid = side.account
        visitor = None if uid else side.visitor(request)
        who = f"user:{uid}" if uid else f"visitor:{visitor}"
        side.limited(who)
        req = AskRequest(question=body.question, mode=body.mode, recency=body.recency,
                         role_weight=body.role_weight, scope=Scope(**body.scope.model_dump()), plan=body.plan,
                         history=body.history_dicts(), compare=body.compare)
        model_on = p.has_model()
        key = None
        if model_on and side.cache_hours > 0:
            last = state.runs(1)
            key = cache_key({"q": plain_question(body.question), **body.model_dump(exclude={"question"}),
                             "model": settings.answer.get("model"), "data": last[0]["run_id"] if last else None,
                             "instructions": app.INSTRUCTIONS_VERSION})
        usage.count_question(state, body.question)
        usage.record_event(state, "ask", visitor)
        if body.history:
            usage.record_event(state, "follow_up", visitor)
        ask = Ask(question=body.question, visitor=visitor, account=uid, limiter_key=who,
                  write=lambda: p.run(req), sources_only=lambda note, free: sources_only(body, note, uid, visitor),
                  cache_key=key, only_sources=body.sources_only, model_available=model_on,
                  follow_up=bool(body.history), mode=body.mode,
                  options=body.model_dump(exclude={"question", "history"}))
        ask.save = lambda final, kept, text: keep(ask, kept, final)
        return sse(side.desk.handle(ask))

    return route, MpsHooks()


ROUTES: dict[str, Callable[[DeskSide], tuple[Route, Hooks]]] = {
    "hansard": mps_route, "wcs": countries_route, "councils": councils_route}
