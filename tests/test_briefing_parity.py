"""The briefing desk against each site's own ``ask`` flow: the same bytes sent, the same rows written.

For Where MPs Stand, Where Countries Stand and Where Councils Stand, each scenario is played twice on the same
scripted pipeline: through the site's real web app (``create_app`` from its checkout, driven through ``/api/ask``),
and through the route the site would have after adopting the package (``briefing_sites.py``). Compared: the status
and the exact bytes of every answer; and, field by field, the rows written to the spending record, the answer
cache, saved briefings and the notes of failures (the site's own tables beside the ``wts_`` ones).

The cases are ADR 0009's: a fresh question; the same again, from the cache; a follow-up; sources only; the
visitor's limit, the daily cap and the monthly cap each reached; one place too many for the visitor and for the
site; the second check of the caps failing; the pipeline raising mid-stream; the model refusing; no records; no
API key; the reader leaving while the briefing is written. Where a checkout is absent, or a library its web app
needs is not installed, the comparison is skipped, saying so.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from briefing_sites import SALT, START, DeskSide, Side, SiteSide, site_code
from test_usage_sites import COUNCILS, COUNTRIES, MPS, SiteFacts, site  # noqa: F401
from wts_core.testing import FixedClock
from wts_core.usage import visitor_code

Q = "What has been said about climate finance since 2020?"
Q2 = "And what did the small island states say?"
EARLIER = [{"question": Q, "answer": "Kenya said that climate finance was too slow."}]

type Sent = list[tuple[int, bytes]]
type Scenario = Callable[[Side], Sent]


def events_of(body: bytes) -> list[Any]:
    out = []
    for chunk in body.decode().split("\n\n"):
        data = [line[6:] for line in chunk.splitlines() if line.startswith("data: ")]
        out.append(json.loads(data[0]) if data else chunk)
    return out


@pytest.fixture
def both(site: SiteFacts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: F811
    """Play a scenario through the site's own flow and through the desk, and compare what each sent and wrote.
    Returns the two sides, for anything more a test wants to say about them."""
    site_code(site)

    def play(scenario: Scenario, *, has_model: bool = True, **usage: Any) -> tuple[SiteSide, DeskSide, Sent]:
        clock = FixedClock(START)
        theirs = SiteSide(site, tmp_path, clock, monkeypatch, has_model=has_model, **usage)
        sent_by_site = scenario(theirs)
        clock.set(START)  # the same moment, for the second telling
        ours = DeskSide(site, tmp_path, clock, monkeypatch, has_model=has_model, **usage)
        sent_by_desk = scenario(ours)
        assert len(sent_by_site) == len(sent_by_desk)
        for (status, body), (our_status, our_body) in zip(sent_by_site, sent_by_desk, strict=True):
            assert our_status == status
            assert events_of(our_body) == events_of(body)  # the readable comparison first
            assert our_body == body  # then every byte
        written, ours_written = theirs.rows(), ours.rows()
        for table in ("spending", "cache", "briefings", "failures"):
            assert ours_written[table] == written[table], table
        assert theirs.pipeline.calls == ours.pipeline.calls
        code = visitor_code(ours.db, "testclient", clock=clock)
        assert SALT == ours.db.get(f"visitor_salt:{START[:10]}")
        assert ours.briefings_today(code) == theirs.briefings_today(code)
        # one record for every question the desk was handed, and never the visitor's code in it
        asked = sum(1 for status, _ in sent_by_desk if status == 200)
        assert len(ours.log.records) == asked
        assert code not in repr(ours.log.records)
        return theirs, ours, sent_by_site

    return play


def types_of(body: bytes) -> list[str]:
    return [e["type"] for e in events_of(body) if isinstance(e, dict)]


def final_of(body: bytes) -> dict[str, Any]:
    return [e for e in events_of(body) if isinstance(e, dict)][-1]


def outcomes(side: DeskSide) -> list[str]:
    return [r.outcome for r in side.log.records]


# ---- written, cached, followed up ------------------------------------------------------------------------------


def test_a_fresh_question_and_the_same_again_from_the_cache(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [side.ask(Q), side.ask("what has been said about  CLIMATE finance "
                                                                  "since 2020?")])
    first, again = final_of(sent[0][1]), final_of(sent[1][1])
    assert first["briefing_id"] == "briefing001" and again["cached"] is True
    assert ("usage" in first) is (site is not COUNCILS)  # Where Councils Stand sends no token counts
    assert types_of(sent[1][1]) == ["plan", "sources", "text", "final"]
    assert theirs.pipeline.calls == ["written"]  # the model was asked once
    assert len(ours.rows()["briefings"]) == 1 and len(ours.rows()["cache"]) == 1
    assert outcomes(ours) == ["completed", "cached"]


def test_a_follow_up_is_cached_on_two_sites_and_written_again_on_the_third(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [side.ask(Q), side.ask(Q2, history=EARLIER),
                                            side.ask(Q2, history=EARLIER)])
    if site is COUNTRIES:  # a follow-up's answer depends on what came before: this site never caches one
        assert theirs.pipeline.calls == ["written"] * 3 and outcomes(ours) == ["completed"] * 3
    else:
        assert theirs.pipeline.calls == ["written"] * 2 and outcomes(ours) == ["completed", "completed", "cached"]
    assert [r.follow_up for r in ours.log.records] == [False, True, True]


def test_a_question_the_model_could_not_read(both, site):  # noqa: F811
    _, ours, sent = both(lambda side: [side.ask(Q, "unread")])
    assert "parse_error" not in sent[0][1].decode()
    assert [f[1] for f in ours.rows()["failures"]] == ([] if site is COUNCILS else ["question reading"])


# ---- sources only, and the limits ------------------------------------------------------------------------------


def test_sources_only(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [side.ask(Q, sources_only=True)])
    assert final_of(sent[0][1])["note"] == site.messages.sources_only
    # who read the question: the model on two sites (for a fraction of a penny), the free rules on the third
    assert theirs.pipeline.calls == ([] if site is COUNTRIES else ["make_plan"])
    assert [r[1] for r in ours.rows()["spending"]] == ([] if site is COUNTRIES else ["parse"])
    assert outcomes(ours) == ["sources_only"]


def test_sources_only_costs_nothing_once_the_sites_budget_is_spent(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [side.ask(Q, sources_only=True)], daily_spend_cap_usd=0.0)
    assert theirs.pipeline.calls == [] and ours.rows()["spending"] == []
    assert events_of(sent[0][1])[0]["plan"]["parser"] == "offline"


def test_the_visitors_limit_stops_new_briefings_but_cached_ones_still_load(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [side.ask(Q), side.ask(Q2), side.ask(Q)], per_visitor_daily_questions=1)
    refused = final_of(sent[1][1])
    assert refused["answer"] is None and refused["note"] == site.messages.with_sources(
        site.messages.visitor_daily_limit)
    assert final_of(sent[2][1])["cached"] is True
    # over their own limit, Where MPs Stand still lets the model read the question while the site's budget lasts
    assert theirs.pipeline.calls == ["written"] + (["make_plan"] if site is MPS else [])
    assert outcomes(ours) == ["completed", "paused_limit", "cached"]


def test_the_daily_cap(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [side.ask(Q)], daily_spend_cap_usd=0.0)
    assert final_of(sent[0][1])["note"] == site.messages.with_sources(site.messages.daily_cap)
    assert theirs.pipeline.calls == [] and outcomes(ours) == ["paused_cap"]


def test_the_monthly_cap(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [side.ask(Q)], monthly_spend_cap_usd=0.0)
    assert final_of(sent[0][1])["note"] == site.messages.with_sources(site.messages.monthly_cap)
    assert theirs.pipeline.calls == [] and outcomes(ours) == ["paused_cap"]


def test_too_many_requests_in_a_minute(both, site):  # noqa: F811
    _, ours, sent = both(lambda side: [side.ask(Q), side.ask(Q2)], requests_per_minute=1)
    assert sent[1][0] == 429 and json.loads(sent[1][1]) == {"detail": site.messages.too_many_requests}


# ---- briefings in progress -------------------------------------------------------------------------------------


def while_one_is_written(side: Side, then: Callable[[], Sent]) -> Sent:
    """Start a briefing that stays in progress, do ``then`` while it is, and let it finish. What was sent: the
    held briefing's answer first, then whatever ``then`` sent."""
    side.pipeline.plays.append("held")
    held: list[Any] = []
    other = side.another_client()
    thread = threading.Thread(target=lambda: held.append(other.post("/api/ask", json={"question": Q})))
    thread.start()
    assert side.pipeline.entered.wait(20)
    try:
        sent = then()
    finally:
        side.pipeline.gate.set()
        thread.join(30)
    return [(held[0].status_code, held[0].content), *sent]


def test_one_place_too_many_for_the_visitor(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [*while_one_is_written(side, lambda: [side.ask(Q2)]), side.ask(Q2)],
                              **{site.at_once_key: 1})
    assert final_of(sent[1][1])["note"] == site.messages.with_sources(site.messages.busy_visitor)
    assert final_of(sent[0][1])["answer"] and final_of(sent[2][1])["answer"]  # the place was given back
    assert sorted(outcomes(ours)) == ["busy", "completed", "completed"]


def test_one_place_too_many_for_the_site(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [*while_one_is_written(side, lambda: [side.ask(Q2)]), side.ask(Q2)],
                              **{site.at_once_key: 5, "briefings_at_once": 1})
    assert final_of(sent[1][1])["note"] == site.messages.with_sources(site.messages.busy_site)
    assert sorted(outcomes(ours)) == ["busy", "completed", "completed"]


def test_the_second_check_of_the_caps_counts_the_others_in_progress(both, site):  # noqa: F811
    """Nothing has been spent to speak of, so the first check passes; with another briefing in progress, reserved
    at its estimated cost, the second does not."""
    theirs, ours, sent = both(lambda side: while_one_is_written(side, lambda: [side.ask(Q2)]),
                              daily_spend_cap_usd=0.05)
    assert final_of(sent[1][1])["note"] == site.messages.with_sources(site.messages.daily_cap)
    assert final_of(sent[0][1])["answer"]
    assert sorted(outcomes(ours)) == ["completed", "paused_cap"]


# ---- when it goes wrong ----------------------------------------------------------------------------------------


def test_the_pipeline_raising_mid_stream(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [side.ask(Q, "raises"), side.ask(Q)], **{site.at_once_key: 1})
    assert final_of(sent[0][1]) == {"type": "error", "message": site.messages.briefing_failed}
    assert final_of(sent[1][1])["answer"] and "cached" not in final_of(sent[1][1])  # written afresh, place free
    assert [r[1] for r in ours.rows()["spending"]] == ["parse", "parse"] + (
        ["interests"] if site is MPS else []) + ["answer"]
    assert [f[1:] for f in ours.rows()["failures"]] == ([] if site is COUNCILS else [
        ("briefing", Q, "RuntimeError: the model's stream broke")])
    assert outcomes(ours) == ["error", "completed"] and ours.log.records[0].error_type == "RuntimeError"


def test_the_model_refusing(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [side.ask(Q, "declined"), side.ask(Q)])
    assert final_of(sent[0][1]) == {"type": "error", "message": site.messages.model_declined}
    assert "cached" not in final_of(sent[1][1])
    # the refused call was paid for: counted on two sites; Where MPs Stand's pipeline does not report it
    assert [r[1] for r in ours.rows()["spending"]][:2] == (["parse", "parse"] if site is MPS else ["parse", "answer"])
    assert outcomes(ours) == ["error", "completed"] and ours.log.records[0].error_type == "ModelDeclined"


def test_no_records(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [side.ask(Q, "no_records"), side.ask(Q)])
    assert final_of(sent[0][1])["answer"]["no_records"] is True and final_of(sent[1][1])["cached"] is True
    assert ours.rows()["briefings"] == [] and len(ours.rows()["cache"]) == 1  # cached, never saved
    assert outcomes(ours) == ["no_records", "cached"]


def test_no_api_key(both, site):  # noqa: F811
    theirs, ours, sent = both(lambda side: [side.ask(Q), side.ask(Q), side.ask(Q, sources_only=True)],
                              has_model=False)
    assert final_of(sent[0][1])["answer"] is None and "API key" in final_of(sent[0][1])["note"]
    written = ours.rows()
    assert written["spending"] == [] and written["cache"] == [] and written["briefings"] == []
    assert outcomes(ours) == ["sources_only"] * 3


def test_the_reader_leaving_while_the_briefing_is_written(both, site):  # noqa: F811
    def scenario(side: Side) -> Sent:
        side.pipeline.plays.append("left")
        stream = side.stream(Q)
        received = b""
        for chunk in stream:
            received += chunk
            if chunk.startswith(b"event: text"):
                break
        stream.close()  # the reader has gone: the server closes the response
        side.pipeline.gate.set()
        assert side.pipeline.closed.wait(20)  # the pipeline was stopped, and with it the model
        for thread in threading.enumerate():
            if thread.name == "sse":
                thread.join(20)
        return [(200, received), side.ask(Q)]

    theirs, ours, sent = both(scenario, **{site.at_once_key: 1})
    # the reading of the question was paid for; the answer never finished, so nothing else is recorded for it
    assert [r[1] for r in ours.rows()["spending"]][:2] == ["parse", "parse"]
    assert len(ours.rows()["briefings"]) == 1 and final_of(sent[1][1])["answer"]  # the place was given back
    assert outcomes(ours) == ["left", "completed"]
    assert ours.log.records[0].left_at == "first_token" and ours.log.records[0].output_tokens == 80  # the reading


# ---- what only Where MPs Stand does ----------------------------------------------------------------------------


def only_mps(facts: SiteFacts) -> None:
    if facts is not MPS:
        pytest.skip("only Where MPs Stand has this step")


def test_a_signed_in_account_has_its_own_limit(both, site):  # noqa: F811
    only_mps(site)

    def scenario(side: Side) -> Sent:
        side.sign_in()
        return [side.ask(Q), side.ask(Q2)]

    theirs, ours, sent = both(scenario, per_user_daily_questions=1)
    assert final_of(sent[1][1])["note"] == site.messages.with_sources(site.messages.account_daily_limit)
    assert {(r[3], r[4]) for r in ours.rows()["spending"]} == {(None, 1)}  # by account, with no visitor's code
    assert outcomes(ours) == ["completed", "paused_limit"]


def test_the_reminder_of_costs_goes_to_this_reader_only(both, site):  # noqa: F811
    only_mps(site)
    theirs, ours, sent = both(lambda side: [side.ask(Q), side.ask(Q)], support_reminder_every=1)
    assert final_of(sent[0][1])["support_reminder"] == 1
    assert "support_reminder" not in final_of(sent[1][1])  # not in the cached copy
    assert "support_reminder" not in json.dumps(ours.rows()["briefings"]) + json.dumps(ours.rows()["cache"])
    assert final_of(sent[0][1])["briefing_key"] == ours.rows()["cache"][0][0]


def test_an_answer_cached_before_briefings_had_addresses_is_given_one(both, site):  # noqa: F811
    only_mps(site)

    def scenario(side: Side) -> Sent:
        first = side.ask(Q)
        side.edit_cache(lambda events: [
            {k: v for k, v in e.items() if k not in ("briefing_id", "prepared_at", "records_up_to")}
            for e in events])
        return [first, side.ask(Q), side.ask(Q)]

    theirs, ours, sent = both(scenario)
    assert [final_of(body)["briefing_id"] for _, body in sent] == ["briefing001", "briefing002", "briefing002"]
    assert len(ours.rows()["briefings"]) == 2
