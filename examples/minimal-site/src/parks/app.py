"""The web app: this site's routes, written around the package's parts.

``build`` makes the site's working parts once (the state database, the parts of the briefing desk and the desk,
reports and statements, the pipeline) and ``create_app`` hangs the routes on them. The routes, the request bodies and the
pages are the site's own; the flow of a briefing is the package's (``BriefingDesk``), and so are the rules of the
right of reply (``Replies``).

Run it with ``parks serve``, or ``uvicorn parks.app:create_app --factory``.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from pathlib import Path
from types import EllipsisType
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from wts_core.briefing import Ask, BriefingDesk, DeskParts, Event, Hooks, TooManyRequests, desk_parts, sse
from wts_core.cli import backup_ages, check_route, last_day_figures
from wts_core.observe import LOGGER, SqliteBriefingLog, json_logging
from wts_core.ports import (
    SYSTEM_CLOCK,
    SYSTEM_RANDOM,
    BriefingConfig,
    Clock,
    Embedder,
    ModelClient,
    Random,
    VectorIndex,
)
from wts_core.replies import Refused, Replies, statement_html
from wts_core.state import StateDB
from wts_core.usage import Limits, Spending, cache_key, client_address, visitor_code

from parks.pipeline import (
    Pipeline,
    configuration,
    data_stamp,
    embedder_from_settings,
    model_from_settings,
    new_index,
)
from parks.site import (
    BACKUPS,
    LOADED_WORDS,
    MESSAGES,
    REPLY_MESSAGES,
    SITE,
    VERIFIER,
    ParksSettings,
    load,
    new_briefing_id,
    open_replies,
    open_state,
)

__all__ = ["AskBody", "Parks", "ParksHooks", "build", "create_app", "start_logging"]

PAGE = Path(__file__).with_name("page.html")
# so that a proxy passes each event on as it is written
STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


# ---- the steps only this site has --------------------------------------------------------------------------------


class ParksHooks(Hooks):
    """This site's own steps in the flow of a briefing. Each hook of the package's does nothing unless a site fills
    it in; this site fills in four."""

    def __init__(self, spending: Spending, limits: Limits, records_up_to: str) -> None:
        self._spending = spending
        self._limits = limits
        self._records_up_to = records_up_to

    def on_cached(self, ask: Ask, events: list[Event]) -> list[Event]:
        """A cached briefing is judged again by today's rules before it is shown: a flag the rules no longer make
        is cleared. Nothing is ever newly flagged."""
        return [{**e, "answer": LOADED_WORDS.still_loaded(VERIFIER.recheck(e.get("answer")))}
                if e.get("type") == "final" else e for e in events]

    def on_event(self, ask: Ask, event: Event) -> Event | None:
        """Token counts are for the spending record, which has them by now. A reader has no use for them, so they
        are in no copy: not sent, not saved, not cached."""
        return {k: v for k, v in event.items() if k != "usage"}

    def finish(self, ask: Ask, final: Event, kept: list[Event]) -> Event:
        """Every copy of a briefing says how far the record ran when it was written. (This hook is given every
        final event of the pipeline, so one with no briefing in it is passed on as it is.)"""
        return {**final, "records_up_to": self._records_up_to} if final.get("answer") else final

    def for_this_reader(self, ask: Ask, final: Event) -> Event:
        """How many briefings this reader may still have today. It is about one reader, so it goes to that reader
        only: what is added here is never saved or cached."""
        if ask.visitor is None or not final.get("answer"):
            return final
        left = self._limits.per_visitor_daily - self._spending.briefings_today(visitor=ask.visitor)
        return {**final, "briefings_left_today": max(left, 0)}


# ---- the site's working parts ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Parks:
    """Everything the routes and the owner's commands work with, made once by ``build``."""

    settings: ParksSettings
    db: StateDB
    parts: DeskParts  # the spending record, the caps, the answer cache, saved briefings: what the desk is made of
    log: SqliteBriefingLog
    replies: Replies
    pipeline: Pipeline
    desk: BriefingDesk
    config: BriefingConfig
    clock: Clock
    random: Random
    check_token: str | None


def build(settings: ParksSettings | None = None, *, model: ModelClient | None | EllipsisType = ...,
          embedder: Embedder | None = None, index: VectorIndex | None = None, clock: Clock = SYSTEM_CLOCK,
          random: Random = SYSTEM_RANDOM, env: Mapping[str, str] | None = None) -> Parks:
    """The site, from its settings. A test passes its own model, embedder, index, clock and chance; left alone,
    each comes from the settings and the system. Nothing is global: two sites can be built in one process."""
    settings = settings or load(env=env)
    db = open_state(settings, clock)
    # Everything the flow of a briefing is made of, from [usage]: prices, limits, the spending record, the caps,
    # the per-minute limiter, the answer cache, saved briefings and the notes of failures, on the one clock. This
    # is also the start-up check: every limit, price and message the flow needs, with whatever is missing named
    # together in one error.
    parts = desk_parts(
        settings, db, MESSAGES,
        new_id=new_briefing_id,
        # this site's names for the two settings the family's sites name differently
        at_once_per_visitor="briefings_at_once_per_visitor", forget_over="forget_idle_visitors_over",
        keep_failures=True,  # a failed briefing is noted for the owner (the privacy notice says for how long)
        # both models must have prices of their own, so a new model is never costed at another's
        require_prices_for=(settings.answer["model"], settings.answer["query_parse_model"]),
        clock=clock, random=random)
    log = SqliteBriefingLog(db, clock=clock)

    embedder = embedder or embedder_from_settings(settings)
    pipeline = Pipeline(settings, model=model_from_settings(settings, env) if model is ... else model,
                        embedder=embedder, index=index or new_index(embedder), spending=parts.spending)
    config = configuration(settings, embedder, log)  # its id worked out and the settings behind it kept, at once

    desk = parts.desk(
        config,
        log=log,  # the record of each briefing, turned on (docs/adr/0012)
        hooks=ParksHooks(parts.spending, parts.limits, pipeline.records_up_to),
        group_of=lambda card: card.get("park"),  # the record counts each briefing's sources by park
    )
    return Parks(settings=settings, db=db, parts=parts, log=log, replies=open_replies(db, clock), pipeline=pipeline,
                 desk=desk, config=config, clock=clock, random=random, check_token=SITE.env("CHECK_TOKEN", env))


def start_logging(settings: ParksSettings, clock: Clock = SYSTEM_CLOCK) -> logging.Handler:
    """Turn the structured log on for this process: one line of JSON for each thing the site notes about its own
    work (``wts_core.observe.log_event``), in ``<data>/logs/briefings.jsonl``. The handler is returned so that
    whoever started it can take it off again."""
    logs = settings.section("logs")
    handler = json_logging(settings.logs_dir / "briefings.jsonl", site=SITE, max_bytes=int(logs["max_bytes"]),
                           keep=int(logs["keep"]), days=int(logs["days"]), clock=clock)
    log = logging.getLogger(LOGGER)
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    return handler


# ---- request bodies ----------------------------------------------------------------------------------------------


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    mode: Literal["summary", "comprehensive"] = "summary"
    park: str | None = Field(default=None, max_length=80)  # the one filter a reader may set
    sources_only: bool = False


class StatementBody(BaseModel):
    name: str = ""
    role: str = ""
    item: str = ""
    text: str = ""
    link: str | None = None
    email: str = ""
    website: str = ""  # the trap: a field people never see and so leave empty


class ReportBody(BaseModel):
    kind: str = ""
    page: str | None = None
    message: str = ""
    contact: str | None = None
    briefing_id: str | None = None
    website: str = ""


# ---- the app -----------------------------------------------------------------------------------------------------


def create_app(parks: Parks | None = None) -> FastAPI:
    """The site's web app. With nothing passed it is the site as it runs: built from its settings, with the
    structured log turned on. A test passes parts it built itself."""
    if parks is None:
        parks = build()
        start_logging(parks.settings, parks.clock)
    settings, desk, pipeline, replies = parks.settings, parks.desk, parks.pipeline, parks.replies
    server = settings.section("server")
    app = FastAPI(title=SITE.name, version=SITE.version, docs_url=None, redoc_url=None)
    app.state.parks = parks

    def visitor_of(request: Request) -> str:
        """The day's code for this visitor. The address itself is never stored or logged."""
        address = client_address(request.headers, request.client.host if request.client else None,
                                 behind_proxy=bool(server["behind_proxy"]),
                                 trust_forwarded_first=bool(server["trust_forwarded_first"]))
        return visitor_code(parks.db, address, clock=parks.clock, random=parks.random)

    def limited(visitor: str) -> None:
        try:
            desk.allow(visitor)
        except TooManyRequests as exc:
            raise HTTPException(429, exc.message) from None

    def is_the_nightly_check(request: Request) -> bool:
        """Whether the request carries the family's check token (docs/adr/0010). Such a question skips the answer
        cache, or it would prove nothing on six nights in seven, and its record is kept apart from readers'."""
        wanted = (parks.check_token or "").strip()
        scheme, _, presented = request.headers.get("authorization", "").partition(" ")
        return bool(wanted) and scheme.lower() == "bearer" and hmac.compare_digest(presented.strip().encode(),
                                                                                  wanted.encode())

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return PAGE.read_text(encoding="utf-8")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "site": SITE.package, "version": SITE.version}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        paused = parks.parts.caps.site_paused()
        return {"briefings": "paused" if paused else "available", "note": paused.message if paused else None,
                "model": pipeline.has_model, "records_up_to": pipeline.records_up_to}

    # ---- a question ------------------------------------------------------------------------------------------

    @app.post("/api/ask")
    def ask(body: AskBody, request: Request) -> StreamingResponse:
        visitor = visitor_of(request)
        limited(visitor)
        question = " ".join(body.question.split())
        if body.park is not None and body.park not in pipeline.parks:
            raise HTTPException(422, "There is no park of that name in the record.")
        check = is_the_nightly_check(request)
        # What a briefing depends on. The model, the instructions' version and a stamp of the record must be here:
        # change any of them and an answer written before is not served again.
        key = cache_key({"question": question.lower(), "mode": body.mode, "park": body.park,
                         "model": settings.answer["model"], "instructions": SITE.instructions_version,
                         "data": data_stamp(settings.minutes_file)}, length=64)
        events = desk.handle(Ask(
            question=question,
            visitor=visitor,
            write=lambda: pipeline.write(question, mode=body.mode, park=body.park),
            sources_only=lambda note, free: pipeline.sources_only(question, note, free=free, mode=body.mode,
                                                                 park=body.park, visitor=visitor),
            cache_key=None if check else key,
            only_sources=body.sources_only,
            model_available=pipeline.has_model,
            mode=body.mode,
            filters_set=("park",) if body.park else (),  # which filters were set, never their values
            kind="check" if check else "reader",
            options={"mode": body.mode, "park": body.park},  # saved with the briefing: what the reader chose
        ))
        return StreamingResponse(sse(events), media_type="text/event-stream", headers=STREAM_HEADERS)

    # ---- a saved briefing, with any statement beside it ------------------------------------------------------

    @app.get("/b/{briefing_id}", response_class=HTMLResponse)
    def briefing(briefing_id: str) -> HTMLResponse:
        saved = parks.parts.archive.get(briefing_id)
        if saved is None:
            raise HTTPException(404, "There is no briefing at this address.")
        address = f"/b/{saved.id}"
        hidden = replies.hidden(address)
        if saved.withdrawn_at:
            body = f"<p>This briefing was withdrawn. {escape(saved.withdrawn_reason or '')}</p>"
        elif hidden:  # hidden while a concern is decided: the note is shown in its place
            body = f"<p>{escape(hidden['note'])}</p>"
        else:
            final = next((e for e in saved.events if e["type"] == "final"), {})
            answer = final.get("answer") or {}
            to_check = int(answer.get("unsupported_segments", 0)) + int(answer.get("citations_invalid", 0))
            sources: list[dict[str, Any]] = next((e["sources"] for e in saved.events if e["type"] == "sources"), [])
            body = (
                f'<pre class="briefing">{escape(answer.get("markdown", ""))}</pre>'
                f"<p>{to_check} point{'' if to_check == 1 else 's'} to check. "
                f"The record runs to {escape(str(final.get('records_up_to', '')))}.</p>"
                "<h2>The minutes this briefing is drawn from</h2><ol>"
                + "".join(f'<li><a href="{escape(s["url"], quote=True)}">{escape(s["title"])}</a></li>'
                          for s in sources)
                + "</ol>"
                # Statements under the right of reply, set apart from the site's own words. They are read from
                # their own tables here and nowhere else: never by the pipeline, the index or the model.
                + "".join(statement_html(s, REPLY_MESSAGES) for s in replies.published(items=[address])))
        page = (f'<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><title>{escape(saved.question)}: '
                f"{escape(SITE.name)}</title></head><body><main><h1>{escape(saved.question)}</h1>{body}"
                '<p><a href="/">Ask another question</a></p></main></body></html>')
        return HTMLResponse(page)

    # ---- reports and the right of reply ----------------------------------------------------------------------

    def refused(exc: Refused) -> HTTPException:
        """The site's own status for a refusal: 429 for a daily limit, 422 for a mistake in the form."""
        return HTTPException(429 if exc.why.startswith("daily_") else 422, str(exc))

    @app.post("/api/statements")
    def send_statement(body: StatementBody, request: Request) -> dict[str, Any]:
        visitor = visitor_of(request)
        limited(visitor)
        try:
            replies.submit(name=body.name, role=body.role, item=body.item, text=body.text, link=body.link,
                           email=body.email, visitor=visitor, trap=body.website)
        except Refused as exc:
            raise refused(exc) from None
        return {"received": True}  # the same answer whether or not the trap was filled

    @app.get("/api/statements")
    def statements(item: str) -> list[dict[str, Any]]:
        """The published statements beside an item: the public fields and nothing else."""
        return replies.published(items=[item])

    @app.post("/api/report")
    def send_report(body: ReportBody, request: Request) -> dict[str, Any]:
        visitor = visitor_of(request)
        limited(visitor)
        try:
            replies.report(kind=body.kind, page=body.page, message=body.message, contact=body.contact,
                           briefing_id=body.briefing_id, visitor=visitor, trap=body.website)
        except Refused as exc:
            raise refused(exc) from None
        if body.briefing_id:
            parks.log.mark(body.briefing_id, reported=True)  # what happened next, on that briefing's record
        return {"received": True}

    # ---- the nightly family check (docs/adr/0010) ------------------------------------------------------------

    # Counts, ages and versions for whoever holds the family's check token, and for no one else: 404 with no
    # token set on this site, 401 for a wrong one. Never a question, a name or a word of a report.
    check = check_route(SITE, token=parks.check_token, replies=replies,
                        backups=lambda: backup_ages(settings.backups_dir, BACKUPS, clock=parks.clock),
                        figures=lambda: last_day_figures(parks.log, clock=parks.clock), clock=parks.clock)

    @app.get("/api/check")
    def api_check(authorization: str | None = Header(None)) -> JSONResponse:
        status_code, body = check(authorization)
        return JSONResponse(body, status_code=status_code)

    return app
