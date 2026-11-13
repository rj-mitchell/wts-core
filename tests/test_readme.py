"""The README's quick start is run, so it cannot rot: the code in the page is the code under test."""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest

README = Path(__file__).resolve().parents[1] / "README.md"


def quick_start() -> str:
    section = README.read_text(encoding="utf-8").split("## Quick start", 1)[1].split("\n## ", 1)[0]
    blocks: list[str] = re.findall(r"```python\n(.*?)```", section, re.S)
    assert len(blocks) == 1, "the quick start is one block of Python"
    return blocks[0]


def loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """The quick start, loaded as the module ``quickstart`` in an empty folder (it keeps its state in ./data)."""
    monkeypatch.chdir(tmp_path)
    module = types.ModuleType("quickstart")
    monkeypatch.setitem(sys.modules, "quickstart", module)
    exec(compile(quick_start(), "README.md (quick start)", "exec"), module.__dict__)  # noqa: S102
    return module


def events(stream: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")]


def test_the_quick_start_gives_a_working_ask_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("fastapi", reason="the quick start is a FastAPI app (the dev group has it)")
    from fastapi.testclient import TestClient

    page = loaded(tmp_path, monkeypatch)
    client = TestClient(page.app)

    first = client.post("/api/ask", json={"question": "What have the councils decided about waste?"})
    assert first.status_code == 200 and first.headers["content-type"].startswith("text/event-stream")
    sent = events(first.text)
    kinds = [e["type"] for e in sent]
    assert kinds[:2] == ["plan", "sources"] and kinds[-1] == "final" and {"text", "citation"} <= set(kinds)
    answer = sent[-1]["answer"]
    assert answer["citations_total"] > 0 and answer["citations_invalid"] == 0  # checked against the sources
    assert sent[-1]["briefing_id"]  # saved at its own address
    assert (tmp_path / "data" / "state.db").exists()

    again = events(client.post("/api/ask", json={"question": "What have the councils decided about waste?"}).text)
    assert again[-1]["cached"] is True and again[-1]["briefing_id"] == sent[-1]["briefing_id"]
    with page.db.connect() as con:  # the cost was recorded once, against a code and not an address
        (calls, visitor), = con.execute("SELECT count(*), min(visitor) FROM wts_spending").fetchall()
    assert calls == 1 and len(visitor) == 24


def test_the_quick_start_refuses_more_requests_a_minute_than_it_allows(tmp_path: Path,
                                                                       monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("fastapi", reason="the quick start is a FastAPI app (the dev group has it)")
    from fastapi.testclient import TestClient

    client = TestClient(loaded(tmp_path, monkeypatch).app)
    answers = [client.post("/api/ask", json={"question": "What was decided?"}).status_code for _ in range(21)]
    assert answers == [200] * 20 + [429]
