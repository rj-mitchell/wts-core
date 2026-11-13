"""A question, from its arrival at ``/api/ask`` to the last event sent, and what is kept of it."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import pytest
from conftest import DOGS, HOURS, ask, events_of, final_of, rows
from fastapi.testclient import TestClient
from parks.app import Parks, build, create_app
from parks.pipeline import scripted_model
from parks.site import MESSAGES, NO_MODEL, NO_RECORDS, ParksSettings
from wts_core.testing import FixedClock, FixedRandom
from wts_core.testing.models import ScriptedModel, load_stream, recorded


def test_a_fresh_question_is_read_searched_written_and_checked(client: TestClient, model: ScriptedModel) -> None:
    events = ask(client, DOGS)
    kinds = [e["type"] for e in events]

    assert kinds[:2] == ["plan", "sources"]
    assert kinds.index("sources") < min(kinds.index("text"), kinds.index("citation"))  # sources before any words
    assert events[0]["plan"] == {"topic": "dogs leads", "park": None, "read_by": "model"}
    assert [s["id"] for s in events[1]["sources"]] == ["m04", "m01", "m08"]  # oldest first
    assert {s["park"] for s in events[1]["sources"]} == {"Alder Park", "Birchfield Common", "Canal Gardens"}

    final = final_of(events)
    answer = final["answer"]
    assert (answer["citations_total"], answer["citations_invalid"], answer["unsupported_segments"]) == (5, 0, 0)
    assert answer["grounded_ratio"] == 1.0
    assert "".join(e["text"] for e in events if e["type"] == "text") == "".join(s["text"] for s in answer["segments"])
    assert final["briefing_id"] and final["model"] == "recorded-briefing"
    # the model was given the minutes found, and nothing but the question and the site's instructions
    (request,) = model.requests
    assert [d.number for d in request.documents] == [1, 2, 3] and request.question == DOGS


def test_the_sites_own_steps_are_hung_on_the_flow(client: TestClient, parks: Parks) -> None:
    events = ask(client, DOGS)
    final = final_of(events)
    # on_event: token counts are in no copy
    assert all("usage" not in e for e in events)
    # finish: every copy says how far the record ran
    assert final["records_up_to"] == "2026-10-20"
    # for_this_reader: sent to this reader, and in neither the saved copy nor the cached one
    assert final["briefings_left_today"] == 29
    saved = parks.archive.get(final["briefing_id"])
    assert saved is not None and saved.question == DOGS and saved.options == {"mode": "summary", "park": None}
    assert [e["type"] for e in saved.events] == ["plan", "sources", "text", "final"]
    assert saved.events[-1]["records_up_to"] == "2026-10-20" and "briefings_left_today" not in saved.events[-1]
    assert "briefings_left_today" not in final_of(ask(client, DOGS))  # the cached copy


def test_what_a_briefing_cost_is_recorded_against_the_days_visitor_code(client: TestClient, parks: Parks) -> None:
    ask(client, DOGS)
    spent = rows(parks, "SELECT kind, model, visitor, input_tokens, output_tokens, cost_usd FROM wts_spending ORDER BY id")
    assert [(r["kind"], r["model"]) for r in spent] == [("parse", "recorded-reading"), ("answer", "recorded-briefing")]
    # priced by each model's own table in settings.toml: 96 in and 14 out; 612 in, 540 read from the cache, 148 out
    assert [r["cost_usd"] for r in spent] == [pytest.approx(0.000166), pytest.approx(0.004218)]
    assert len({r["visitor"] for r in spent}) == 1 and len(spent[0]["visitor"]) == 24
    assert "testclient" not in str(spent)  # a code, never the address


def test_the_same_question_again_comes_from_the_cache_and_costs_nothing(client: TestClient, parks: Parks,
                                                                        model: ScriptedModel) -> None:
    first = final_of(ask(client, DOGS))
    again = ask(client, "  what have PARK committees decided about dogs? ")  # case and spacing do not matter

    assert [e["type"] for e in again] == ["plan", "sources", "text", "final"]
    assert final_of(again)["cached"] is True and final_of(again)["briefing_id"] == first["briefing_id"]
    assert final_of(again)["answer"] == first["answer"]
    assert len(model.requests) == 1  # the model wrote one briefing
    assert len(rows(parks, "SELECT 1 FROM wts_spending")) == 2  # and nothing more was spent
    assert len(rows(parks, "SELECT 1 FROM wts_briefings")) == 1


def test_a_visitor_at_the_daily_limit_is_shown_the_minutes_with_a_note(load_site: Callable[..., ParksSettings],
                                                                       model: ScriptedModel,
                                                                       clock: FixedClock) -> None:
    parks = build(load_site(**{"usage.per_visitor_daily_questions": 1}), model=model, clock=clock,
                  random=FixedRandom(), env={})
    client = TestClient(create_app(parks))
    ask(client, DOGS)
    events = ask(client, HOURS)

    assert [e["type"] for e in events] == ["plan", "sources", "final"]
    assert events[0]["plan"]["read_by"] == "rules"  # a refused question must cost nothing to read
    assert [s["id"] for s in events[1]["sources"]] == ["m07", "m02", "m09"]  # the sources still help
    assert final_of(events)["answer"] is None
    assert final_of(events)["note"] == MESSAGES.visitor_daily_limit + " The minutes found are shown below."
    assert len(model.requests) == 1 and len(rows(parks, "SELECT 1 FROM wts_spending")) == 2  # nothing more spent
    # tomorrow the visitor may ask again
    clock.advance(days=1)
    assert final_of(ask(client, HOURS))["answer"] is not None


def test_sources_only_finds_the_minutes_and_writes_no_briefing(client: TestClient, parks: Parks,
                                                               model: ScriptedModel) -> None:
    events = ask(client, DOGS, sources_only=True)

    assert [e["type"] for e in events] == ["plan", "sources", "final"]
    assert final_of(events) == {"type": "final", "answer": None, "usage": None, "note": MESSAGES.sources_only}
    assert not model.requests  # no briefing was asked for
    # the model read the question: the site recorded that itself, since these events carry no token counts,
    # and told the briefing's record what it cost (current_stages().spent)
    assert [(r["kind"], r["cost_usd"]) for r in rows(parks, "SELECT kind, cost_usd FROM wts_spending")] \
        == [("parse", pytest.approx(0.000166))]
    (record,) = parks.log.since(clock_start(parks))
    assert (record.outcome, record.cost_usd, record.input_tokens) == ("sources_only", pytest.approx(0.000166), 96)


def clock_start(parks: Parks) -> str:
    return (parks.clock.now() - timedelta(days=1)).isoformat()


def test_more_questions_in_a_minute_than_the_site_allows_is_a_429(load_site: Callable[..., ParksSettings],
                                                                  model: ScriptedModel, clock: FixedClock) -> None:
    parks = build(load_site(**{"usage.requests_per_minute": 2}), model=model, clock=clock, env={})
    client = TestClient(create_app(parks))
    ask(client, DOGS)
    ask(client, DOGS)
    refused = client.post("/api/ask", json={"question": DOGS})
    assert refused.status_code == 429 and refused.json() == {"detail": MESSAGES.too_many_requests}
    clock.advance(seconds=61)
    assert client.post("/api/ask", json={"question": DOGS}).status_code == 200


def test_one_record_is_written_for_every_question_and_names_no_reader(client: TestClient, parks: Parks) -> None:
    final = final_of(ask(client, DOGS))
    ask(client, DOGS)
    written, cached = parks.log.since(clock_start(parks))

    assert (written.outcome, cached.outcome) == ("completed", "cached")
    assert written.kind == "reader" and written.question == DOGS and written.mode == "summary"
    assert written.briefing_id == cached.briefing_id == final["briefing_id"]
    assert written.sources == 3
    assert written.spread == {"Alder Park": 1, "Birchfield Common": 1, "Canal Gardens": 1}  # group_of: by park
    assert (written.citations_total, written.citations_invalid, written.unsupported) == (5, 0, 0)
    assert (written.input_tokens, written.cache_read_tokens, written.output_tokens) == (96 + 612, 540, 14 + 148)
    assert written.cost_usd == pytest.approx(0.004384) and cached.cost_usd == 0
    # the configuration it ran with, and the settings behind the id, kept once
    assert written.config_id == parks.config["config_id"] and written.model == "recorded-briefing"
    assert written.instructions == "2026-11-13"
    stored = parks.log.config(written.config_id)
    assert stored is not None and stored["ranking"]["max_per_park"] == 2
    # every stage was reached: those the desk sees for itself, and those the pipeline marks
    for stage in ("t_parse", "t_search", "t_rank", "t_sources_sent", "t_first_token", "t_written", "t_checked"):
        assert getattr(written, stage) is not None, stage
    # nothing in the record identifies the reader
    (code,) = {r["visitor"] for r in rows(parks, "SELECT visitor FROM wts_spending")}
    assert code not in str(rows(parks, "SELECT * FROM wts_briefing_log"))


def test_a_briefing_whose_citations_do_not_match_its_sources_is_flagged_not_hidden(
        settings: ParksSettings, clock: FixedClock) -> None:
    # the recording made for dogs, replayed over the minutes found for opening hours: nothing it cites is there
    wrong = ScriptedModel(settings.recordings_dir / "dogs.jsonl", structured={"topic": "open close"})
    client = TestClient(create_app(build(settings, model=wrong, clock=clock, env={})))
    answer = final_of(ask(client, HOURS))["answer"]

    assert (answer["citations_total"], answer["citations_invalid"]) == (5, 5)
    assert answer["grounded_ratio"] == 0.0
    assert {s["status"] for s in answer["segments"]} == {"connective", "invalid"}  # shown as such to the reader


def test_a_loaded_word_of_the_sites_own_and_an_unsupported_sentence_are_marked(settings: ParksSettings,
                                                                              clock: FixedClock) -> None:
    hours = scripted_model(settings.recordings_dir / "opening-hours.jsonl")
    client = TestClient(create_app(build(settings, model=hours, clock=clock, env={})))
    answer = final_of(ask(client, HOURS))["answer"]

    (flagged,) = [s for s in answer["segments"] if s["status"] == "unsupported"]
    assert flagged["text"].startswith("The shorter winter hours leave Canal Gardens neglected")
    assert [m["word"] for m in flagged["loaded"]] == ["neglected"]  # on this site's list, not the family's
    assert (answer["unsupported_segments"], answer["loaded_words"], answer["citations_invalid"]) == (1, 1, 0)


def test_with_nothing_in_the_record_the_site_says_so_and_asks_no_model(settings: ParksSettings,
                                                                       clock: FixedClock) -> None:
    model = ScriptedModel(settings.recordings_dir / "dogs.jsonl", structured={"topic": "ice rink"})
    parks = build(settings, model=model, clock=clock, env={})
    events = ask(TestClient(create_app(parks)), "What have committees said about an ice rink?")

    assert events[1]["sources"] == []
    answer = final_of(events)["answer"]
    assert answer["no_records"] is True and answer["markdown"] == NO_RECORDS
    assert "briefing_id" not in final_of(events) and not model.requests  # nothing written, nothing saved
    assert [r.outcome for r in parks.log.since(clock_start(parks))] == ["no_records"]


def test_when_the_model_says_the_minutes_do_not_answer_it_is_a_no_records_briefing(settings: ParksSettings,
                                                                                   clock: FixedClock) -> None:
    parking = scripted_model(settings.recordings_dir / "parking.jsonl")
    parks = build(settings, model=parking, clock=clock, env={})
    events = ask(TestClient(create_app(parks)), "Have any committees decided to charge for parking?")

    assert [s["id"] for s in events[1]["sources"]] == ["m06"]
    assert final_of(events)["answer"]["no_records"] is True  # the verifier knows this site's "no records" words
    assert [r.outcome for r in parks.log.since(clock_start(parks))] == ["no_records"]
    assert not rows(parks, "SELECT 1 FROM wts_briefings")


def test_with_no_model_the_minutes_are_shown_and_nothing_is_spent(settings: ParksSettings, clock: FixedClock) -> None:
    parks = build(settings, model=None, clock=clock, env={})
    client = TestClient(create_app(parks))
    events = ask(client, DOGS)

    assert events[0]["plan"]["read_by"] == "rules"
    assert [s["id"] for s in events[1]["sources"]] == ["m04", "m01", "m08"]
    assert final_of(events) == {"type": "final", "answer": None, "note": NO_MODEL}
    assert not rows(parks, "SELECT 1 FROM wts_spending")
    assert client.get("/api/status").json()["model"] is False


def test_a_model_that_declines_is_an_error_for_the_reader_and_is_still_paid_for(settings: ParksSettings,
                                                                               clock: FixedClock) -> None:
    declines = ScriptedModel(load_stream(recorded("refusal")), structured={"topic": "dogs"})
    parks = build(settings, model=declines, clock=clock, env={})
    events = ask(TestClient(create_app(parks)), DOGS)

    assert events[-1] == {"type": "error", "message": MESSAGES.model_declined}  # no token counts are sent
    assert [r["kind"] for r in rows(parks, "SELECT kind FROM wts_spending")] == ["parse", "answer"]
    assert [(r["kind"], r["question"]) for r in rows(parks, "SELECT kind, question FROM wts_failures")] \
        == [("briefing", DOGS)]
    (record,) = parks.log.since(clock_start(parks))
    assert (record.outcome, record.error_type) == ("error", "ModelDeclined")
    assert not rows(parks, "SELECT 1 FROM wts_briefings") and not rows(parks, "SELECT 1 FROM wts_answer_cache")


def test_a_pipeline_that_breaks_never_leaves_the_reader_waiting(settings: ParksSettings, clock: FixedClock) -> None:
    breaks = ScriptedModel(load_stream(recorded("cited_briefing"))[:3], structured={"topic": "dogs"},
                           error=RuntimeError("the connection dropped"))
    parks = build(settings, model=breaks, clock=clock, env={})
    events = ask(TestClient(create_app(parks)), DOGS)

    assert events[-1] == {"type": "error", "message": MESSAGES.briefing_failed}
    (record,) = parks.log.since(clock_start(parks))
    assert (record.outcome, record.error_type) == ("error", "RuntimeError")  # the class, never the message


def test_the_nightly_checks_question_skips_the_cache_and_is_kept_apart(settings: ParksSettings, model: ScriptedModel,
                                                                       clock: FixedClock) -> None:
    parks = build(settings, model=model, clock=clock, env={"PARKS_CHECK_TOKEN": "a-long-random-value"})
    client = TestClient(create_app(parks))
    ask(client, DOGS)
    checked = ask(client, DOGS, headers={"Authorization": "Bearer a-long-random-value"})

    assert "cached" not in final_of(checked) and len(model.requests) == 2  # asked afresh, not served from the cache
    assert [r.outcome for r in parks.log.since(clock_start(parks))] == ["completed"]  # readers' questions only
    assert [r.kind for r in parks.log.since(clock_start(parks), kinds=("check",))] == ["check"]
    # a wrong token is an ordinary reader's question
    assert final_of(ask(client, DOGS, headers={"Authorization": "Bearer wrong"}))["cached"] is True


def test_a_reader_may_choose_a_park_and_the_record_notes_only_that_a_filter_was_set(client: TestClient,
                                                                                   parks: Parks) -> None:
    events = ask(client, DOGS, park="Alder Park", sources_only=True)
    assert [s["id"] for s in events[1]["sources"]] == ["m01"]
    (record,) = parks.log.since(clock_start(parks))
    assert record.filters_set == ("park",) and "Alder" not in str(record.filters_set)
    assert client.post("/api/ask", json={"question": DOGS, "park": "Hyde Park"}).status_code == 422


def test_the_page_and_the_health_check_answer(client: TestClient) -> None:
    home = client.get("/")
    assert home.status_code == 200 and "<h1>Where Parks Stand</h1>" in home.text
    assert client.get("/api/health").json() == {"ok": True, "site": "parks", "version": "0.1.0"}
    assert client.get("/api/status").json() == {"briefings": "available", "note": None, "model": True,
                                                "records_up_to": "2026-10-20"}


def test_the_stream_is_server_sent_events_as_every_site_sends_them(client: TestClient) -> None:
    response = client.post("/api/ask", json={"question": DOGS, "sources_only": True})
    assert response.headers["cache-control"] == "no-cache" and response.headers["x-accel-buffering"] == "no"
    first = response.text.split("\n\n")[0]
    assert first.startswith('event: plan\ndata: {"type": "plan"')
    assert [e["type"] for e in events_of(response.text)] == ["plan", "sources", "final"]
