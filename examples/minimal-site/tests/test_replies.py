"""Reports and the right of reply: a statement sent, published by the owner and shown beside a saved briefing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from wts_core.replies import PUBLIC_FIELDS, NotDone
from wts_core.testing import FixedClock, FixedRandom, assert_statements_stay_out
from wts_core.testing.index import MemoryIndex, RecordingEmbedder
from wts_core.testing.models import ScriptedModel

from conftest import DOGS, ask, final_of, rows
from parks.app import Parks, build, create_app
from parks.site import REPLY_MESSAGES, ParksSettings

WORDS = "The committee's decision on dogs was taken after a full consultation.\n\nWe stand by it."


@pytest.fixture
def briefing(client: TestClient) -> str:
    """The address of a saved briefing: something a statement can sit beside."""
    return f"/b/{final_of(ask(client, DOGS))['briefing_id']}"


def statement(item: str, **changed: Any) -> dict[str, Any]:
    return {"name": "Priya Raman", "role": "Chair, Alder Park Committee", "item": item, "text": WORDS,
            "link": "https://alderpark.example/minutes", "email": "chair@alderpark.example", **changed}


def test_a_statement_is_sent_published_by_the_owner_and_shown_beside_the_briefing(client: TestClient, parks: Parks,
                                                                                 briefing: str) -> None:
    # sent with the briefing's full address, as someone would paste it
    sent = client.post("/api/statements", json=statement(f"https://whereparksstand.example{briefing}"))
    assert sent.status_code == 200 and sent.json() == {"received": True}
    assert "Statement from" not in client.get(briefing).text  # waiting: nothing is shown until the owner decides
    assert parks.replies.waiting().statements == 1

    (waiting,) = parks.replies.statements("pending")
    with pytest.raises(NotDone):  # the owner must say how the sender was confirmed
        parks.replies.publish(waiting["id"], checked="")
    parks.replies.publish(waiting["id"], checked="Replied from the committee's published address.")

    page = client.get(briefing).text
    assert "Statement from Priya Raman, 13 November 2026" in page  # the glossary's heading
    assert "In their own words. Not checked or endorsed by Where Parks Stand." in page
    assert "data-nosnippet" in page  # a search engine never quotes it as the site's own words
    assert "<p>The committee&#x27;s decision on dogs was taken after a full consultation.</p><p>We stand by it.</p>" \
        in page
    assert 'rel="nofollow ugc noopener noreferrer"' in page
    assert "chair@alderpark.example" not in page  # the confirming address is never shown


def test_the_public_sees_the_public_fields_of_a_statement_and_nothing_else(client: TestClient, parks: Parks,
                                                                           briefing: str) -> None:
    client.post("/api/statements", json=statement(briefing))
    parks.replies.publish(parks.replies.statements("pending")[0]["id"], checked="Confirmed by telephone.")
    (shown,) = client.get("/api/statements", params={"item": briefing}).json()
    assert tuple(shown) == PUBLIC_FIELDS
    assert shown["item"] == briefing and shown["date"] == "2026-11-13"


@pytest.mark.parametrize("changed, said", [
    ({"item": "/parks/alder-park"}, "Please paste the address of a briefing: it looks like /b/ and then some letters."),
    ({"item": "https://elsewhere.example/b/token000002"}, "That address is not on this site. Please paste the address "
                                                        "of a briefing."),
    ({"item": "/b/nosuchbriefing"}, REPLY_MESSAGES.item_not_shown),
    ({"text": "word " * 151}, "A statement may be up to 150 words. Yours has 151."),
    ({"email": "not an address"}, REPLY_MESSAGES.bad_email),
    ({"link": "javascript:alert(1)"}, REPLY_MESSAGES.bad_link),
])
def test_what_cannot_be_accepted_is_refused_in_the_sites_words(client: TestClient, parks: Parks, briefing: str,
                                                               changed: dict[str, Any], said: str) -> None:
    refused = client.post("/api/statements", json={**statement(briefing), **changed})
    assert refused.status_code == 422 and refused.json() == {"detail": said}
    assert not parks.replies.statements()  # refused, never cut to fit


def test_a_filled_trap_field_is_answered_as_if_all_were_well_and_nothing_is_kept(client: TestClient, parks: Parks,
                                                                                briefing: str) -> None:
    sent = client.post("/api/statements", json=statement(briefing, website="https://spam.example"))
    assert sent.json() == {"received": True} and not parks.replies.statements()


def test_the_daily_limit_on_statements_is_a_429(client: TestClient, briefing: str) -> None:
    for _ in range(3):
        assert client.post("/api/statements", json=statement(briefing)).status_code == 200
    over = client.post("/api/statements", json=statement(briefing))
    assert over.status_code == 429 and over.json() == {"detail": REPLY_MESSAGES.daily_statements}


def test_a_report_waits_for_the_owner_and_is_noted_on_the_briefings_record(client: TestClient, parks: Parks,
                                                                          briefing: str) -> None:
    sent = client.post("/api/report", json={"kind": "error", "page": briefing, "contact": "reader@example.org",
                                            "message": "The date given for the towpath rule looks wrong.",
                                            "briefing_id": briefing.removeprefix("/b/")})
    assert sent.json() == {"received": True}
    waiting = parks.replies.waiting()
    assert (waiting.reports, waiting.oldest_working_days) == (1, 0)
    (record,) = parks.log.since("2026-11-12T00:00:00+00:00")
    assert record.reported is True  # what happened next, on the record of that briefing

    (report,) = parks.replies.reports()
    parks.replies.close(report["id"], outcome="resolved", note="Checked against the minute: the date is right.",
                        public_note="A reader asked about a date in a briefing on dogs. It was checked and is right.")
    assert rows(parks, "SELECT contact FROM wts_reports") == [{"contact": None}]  # only ever kept to reply
    assert [c["note"] for c in parks.replies.corrections()] \
        == ["A reader asked about a date in a briefing on dogs. It was checked and is right."]
    short = client.post("/api/report", json={"kind": "error", "message": "Wrong"})
    assert short.status_code == 422 and short.json() == {"detail": REPLY_MESSAGES.report_too_short}


def test_a_briefing_hidden_while_a_concern_is_decided_shows_the_note_instead(client: TestClient, parks: Parks,
                                                                            briefing: str) -> None:
    client.post("/api/statements", json=statement(briefing))
    parks.replies.publish(parks.replies.statements("pending")[0]["id"], checked="Confirmed by telephone.")
    parks.replies.hide(briefing, "This briefing is hidden while a concern about it is looked into.")

    page = client.get(briefing).text
    assert "This briefing is hidden while a concern about it is looked into." in page
    assert "Dogs on leads" not in page and "Statement from" not in page  # a statement is hidden with its item
    assert client.post("/api/statements", json=statement(briefing)).status_code == 422  # and none is taken beside it

    parks.replies.unhide(briefing)
    assert "Dogs on leads" in client.get(briefing).text


def test_a_withdrawn_briefing_says_so_at_its_address(client: TestClient, parks: Parks, briefing: str) -> None:
    parks.parts.archive.withdraw(briefing.removeprefix("/b/"), "It gave the wrong year for a decision.")
    page = client.get(briefing).text
    assert "This briefing was withdrawn. It gave the wrong year for a decision." in page
    assert "Dogs on leads" not in page
    assert client.get("/b/nosuchbriefing").status_code == 404


def test_a_statement_never_reaches_the_model_the_index_or_the_record(
        settings: ParksSettings, model: ScriptedModel, clock: FixedClock, log_lines: Callable[[], list[str]]) -> None:
    # the site's real pipeline and routes, over the package's recording fakes
    embedder = RecordingEmbedder()
    index = MemoryIndex(embedder)
    parks = build(settings, model=model, embedder=embedder, index=index, clock=clock, random=FixedRandom(), env={})
    client = TestClient(create_app(parks))
    beside = f"/b/{final_of(ask(client, DOGS))['briefing_id']}"

    # The package's own check (docs/adr/0008): it publishes a statement carrying a marker beside the briefing,
    # asks a question about the same subject, and fails if the marker is in any request to the model, any text
    # given to the embedder, the index, an event sent, any table but the right of reply's own, or a log line.
    assert_statements_stay_out(
        replies=parks.replies, ask=lambda question: ask(client, question), model=model, embedder=embedder,
        index=index, state=parks.db, log_lines=log_lines, item=beside,
        question="Which park committees have made rules about dogs on leads?")
    assert "wtsmarker" in client.get(beside).text  # and yet the statement is shown, beside the briefing
