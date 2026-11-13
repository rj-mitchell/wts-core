"""What is kept about a reader: nothing but the day's code beside the spending, and the question where the privacy
notice says a question is kept."""

from __future__ import annotations

import json
from collections.abc import Callable

from fastapi.testclient import TestClient
from wts_core.observe import FIELDS

from conftest import ask, rows
from parks.app import Parks

CANARY = "What did the committees decide about dogs and the xylophonecanary?"


def test_the_structured_log_holds_stages_and_times_and_never_the_question(client: TestClient, parks: Parks,
                                                                         log_lines: Callable[[], list[str]]) -> None:
    ask(client, CANARY)
    lines = [json.loads(line) for line in log_lines()]

    assert [line["stage"] for line in lines] == ["searched", "ranked", "written"]
    assert all(set(line) <= set(FIELDS) and line["site"] == "parks" and line["event"] == "briefing.stage"
               for line in lines)
    assert "xylophonecanary" not in "\n".join(log_lines())


def test_nothing_from_the_request_is_stored_but_the_days_code_and_the_question(client: TestClient, parks: Parks,
                                                                              log_lines: Callable[[], list[str]]) -> None:
    # TODO(wts_core.cli): replace with wts_core.testing.assert_no_reader_data once it is on the package branch.
    ask(client, CANARY, headers={"User-Agent": "a-browser-like-no-other"})
    kept = {table: str(rows(parks, f"SELECT * FROM {table}")) for table in sorted(parks.db.tables())}
    everything = "\n".join(kept.values()) + "\n".join(log_lines())

    assert "testclient" not in everything and "a-browser-like-no-other" not in everything  # no address, no header
    assert {table for table, held in kept.items() if "xylophonecanary" in held} \
        == {"wts_briefing_log", "wts_briefings"}
    (code,) = {r["visitor"] for r in rows(parks, "SELECT visitor FROM wts_spending")}
    assert {table for table, held in kept.items() if code in held} == {"wts_spending"}
