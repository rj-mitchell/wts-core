"""What is kept about a reader: nothing but the day's code beside the spending, and the question where the privacy
notice says a question is kept."""

from __future__ import annotations

import json
from collections.abc import Callable

from fastapi.testclient import TestClient
from wts_core.observe import FIELDS
from wts_core.testing import assert_no_reader_data

from conftest import ask, rows
from parks.app import Parks

CANARY = "What did the committees decide about dogs and the xylophonecanary?"


def test_the_structured_log_holds_stages_and_times_and_never_the_question(client: TestClient, parks: Parks,
                                                                         log_lines: Callable[[], list[str]]) -> None:
    ask(client, CANARY)
    lines = [json.loads(line) for line in log_lines()]

    # the desk writes them, once the site has given the log a handler: each stage reached, then how it ended
    assert [line["stage"] for line in lines] == ["parsed", "searched", "ranked", "sources_sent", "first_token",
                                                 "written", "checked", None]
    assert [line["event"] for line in lines] == ["briefing.stage"] * 7 + ["briefing.completed"]
    assert all(set(line) == set(FIELDS) and line["site"] == "parks" for line in lines)
    # every line names its briefing by the id of the briefing's record, and by nothing else
    (record,) = parks.log.since("2026-11-13T00:00:00+00:00")
    assert {line["briefing"] for line in lines} == {record.id} and len(record.id) == 11
    assert "xylophonecanary" not in "\n".join(log_lines())


def test_nothing_about_the_reader_is_kept_but_the_days_code_and_the_question(client: TestClient, parks: Parks,
                                                                            log_lines: Callable[[], list[str]]) -> None:
    ask(client, CANARY, headers={"User-Agent": "a-browser-like-no-other"})
    (code,) = {r["visitor"] for r in rows(parks, "SELECT visitor FROM wts_spending")}

    # The package's own check: the address is in no table and no log line; the day's code only beside the
    # spending; the question only where the privacy notice says a question is kept (docs/adr/0012).
    assert_no_reader_data(parks.db, log_lines(), question=CANARY, address="testclient", visitor=code)
    # and nothing else the request carried was stored either
    everything = "".join(str(rows(parks, f"SELECT * FROM {table}")) for table in sorted(parks.db.tables()))
    assert "a-browser-like-no-other" not in everything
