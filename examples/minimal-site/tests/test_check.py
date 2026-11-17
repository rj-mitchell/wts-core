"""``GET /api/check``: what the nightly family check asks of every site (docs/adr/0010)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from wts_core.testing import FixedClock
from wts_core.testing.models import ScriptedModel

from conftest import DOGS, ask
from parks.app import Parks, build, create_app
from parks.site import ParksSettings

TOKEN = {"Authorization": "Bearer a-long-random-value"}


def test_with_no_token_set_the_address_is_not_there(client: TestClient) -> None:
    assert client.get("/api/check").status_code == 404
    assert client.get("/api/check", headers=TOKEN).status_code == 404


def test_the_check_answers_only_to_the_token_and_with_counts_and_ages_only(settings: ParksSettings,
                                                                          model: ScriptedModel,
                                                                          clock: FixedClock) -> None:
    parks: Parks = build(settings, model=model, clock=clock, env={"PARKS_CHECK_TOKEN": "a-long-random-value"})
    client = TestClient(create_app(parks))
    assert client.get("/api/check").status_code == 401
    assert client.get("/api/check", headers={"Authorization": "Bearer wrong"}).status_code == 401

    ask(client, DOGS)
    client.post("/api/report", json={"kind": "error", "message": "The towpath rule is given the wrong date."})
    clock.advance(minutes=5)
    answer = client.get("/api/check", headers=TOKEN)

    assert answer.status_code == 200
    body = answer.json()
    assert body["site"] == "parks" and body["versions"]["site"] == "0.1.0"
    assert body["waiting"] == {"reports": 1, "statements": 0, "hidden": 0, "oldest_working_days": 0}
    assert body["backups"] == {"newest_hours": None, "offsite_hours": None, "offsite_ok": None}
    assert body["figures"]["briefings"] == 1 and body["figures"]["by_outcome"] == {"completed": 1}
    assert "dogs" not in answer.text.lower() and "towpath" not in answer.text  # no question, no word of a report
