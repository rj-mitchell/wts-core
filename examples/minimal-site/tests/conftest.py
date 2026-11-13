"""What the example's tests share: the site built in a temporary folder, on a clock that stands still."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from parks.app import Parks, build, create_app, start_logging
from parks.pipeline import scripted_model
from parks.site import ParksSettings, load
from wts_core.observe import LOGGER
from wts_core.testing import FixedClock, FixedRandom
from wts_core.testing.models import ScriptedModel

DOGS = "What have park committees decided about dogs?"
HOURS = "When do the parks open and close?"


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock("2026-11-13T12:00:00+00:00")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def load_site(data_dir: Path) -> Callable[..., ParksSettings]:
    """The site's settings with its data in a temporary folder, and any setting overridden: ``section.key=value``."""

    def loaded(**overrides: Any) -> ParksSettings:
        return load(env={"PARKS_DATA_DIR": str(data_dir)}, **overrides)

    return loaded


@pytest.fixture
def settings(load_site: Callable[..., ParksSettings]) -> ParksSettings:
    return load_site()


@pytest.fixture
def model(settings: ParksSettings) -> ScriptedModel:
    """The scripted model the site uses by default, kept so that a test can read what it was asked."""
    scripted = scripted_model(settings.recordings_dir / "dogs.jsonl")
    assert isinstance(scripted, ScriptedModel)
    return scripted


@pytest.fixture
def parks(settings: ParksSettings, model: ScriptedModel, clock: FixedClock) -> Parks:
    return build(settings, model=model, clock=clock, random=FixedRandom(), env={})


@pytest.fixture
def client(parks: Parks) -> TestClient:
    return TestClient(create_app(parks))


@pytest.fixture
def log_lines(settings: ParksSettings, clock: FixedClock) -> Iterator[Callable[[], list[str]]]:
    """Turn the structured log on for one test; the function given reads the lines written so far."""
    handler = start_logging(settings, clock)

    def lines() -> list[str]:
        handler.flush()
        return [line for path in sorted(settings.logs_dir.glob("briefings.jsonl*"))
                for line in path.read_text(encoding="utf-8").splitlines()]

    yield lines
    logging.getLogger(LOGGER).removeHandler(handler)
    handler.close()


def ask(client: TestClient, question: str, **body: Any) -> list[dict[str, Any]]:
    """Ask a question and read the whole stream: the events a reader's browser would be sent."""
    response = client.post("/api/ask", json={"question": question, **body.pop("json", {}), **body},
                           headers=body.pop("headers", None))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return events_of(response.text)


def events_of(stream: str) -> list[dict[str, Any]]:
    """The events in a body of server-sent events; comment lines (the keep-alive) are passed over."""
    found = []
    for block in stream.split("\n\n"):
        data = [line[6:] for line in block.split("\n") if line.startswith("data: ")]
        if data:
            found.append(json.loads("\n".join(data)))
    return found


def final_of(events: list[dict[str, Any]]) -> dict[str, Any]:
    assert events[-1]["type"] == "final", events[-1]
    return events[-1]


def rows(parks: Parks, sql: str) -> list[dict[str, Any]]:
    with parks.db.connect() as con:
        return [dict(row) for row in con.execute(sql)]
