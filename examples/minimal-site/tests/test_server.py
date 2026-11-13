"""The site as it really runs: started with its own command, asked over HTTP, its answer read as a stream."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from conftest import DOGS


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def server(tmp_path: Path) -> Iterator[str]:
    """``parks serve`` in a process of its own, on a free port, with its data in a temporary folder."""
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith("PARKS_")}
    process = subprocess.Popen([sys.executable, "-m", "parks.cli", "serve", "--port", str(port)],
                               env={**env, "PARKS_DATA_DIR": str(tmp_path / "data")},
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    address = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise AssertionError(f"the server stopped as it started:\n{process.stdout.read() if process.stdout else ''}")
            try:
                if httpx.get(f"{address}/api/health", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.1)
        else:
            raise AssertionError("the server did not start within ten seconds")
        yield address
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_the_real_server_streams_a_briefing_over_http(server: str, tmp_path: Path) -> None:
    events = []
    with httpx.stream("POST", f"{server}/api/ask", json={"question": DOGS}, timeout=30) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():  # each event is read as it arrives
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    kinds = [e["type"] for e in events]
    assert kinds[:2] == ["plan", "sources"] and kinds[-1] == "final" and "text" in kinds
    final = events[-1]
    assert final["answer"]["citations_total"] == 5 and final["answer"]["citations_invalid"] == 0
    # the briefing is at its own address, and the same question again is served from the cache
    page = httpx.get(f"{server}/b/{final['briefing_id']}")
    assert page.status_code == 200 and "Dogs on leads" in page.text
    again = httpx.post(f"{server}/api/ask", json={"question": DOGS}, timeout=30)
    assert '"cached": true' in again.text
    # the site as it runs writes the structured log: stages and times, and no word of the question
    log = (tmp_path / "data" / "logs" / "briefings.jsonl").read_text(encoding="utf-8")
    assert [json.loads(line)["stage"] for line in log.splitlines()] == ["searched", "ranked", "written"]
    assert "dogs" not in log.lower()
