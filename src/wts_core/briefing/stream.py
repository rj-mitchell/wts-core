"""The streamer: a briefing's events as server-sent events, with a comment line during long silences.

The same code in Where MPs Stand, Where Countries Stand and Where Councils Stand (each one's ``api/app.py``), moved
here as it is: what a reader receives is the same, byte for byte. One thing is added that no reader can see: the
thread that works the events out starts with a copy of the caller's context, so anything the caller set in a
context variable (the briefing desk's stage timings among them) is there when the site's pipeline runs.
"""

from __future__ import annotations

import contextvars
import json
import queue
import threading
from collections.abc import Iterator, Mapping
from typing import Any

__all__ = ["KEEP_ALIVE_SECONDS", "sse"]

KEEP_ALIVE_SECONDS = 15  # on all three sites: proxies close a response that sends nothing for much longer


def sse(events: Iterator[Mapping[str, Any]], keep_alive: float = KEEP_ALIVE_SECONDS) -> Iterator[bytes]:
    """Server-sent events, with a comment line after a few seconds of silence (while the model is thinking): proxies
    close a response that sends nothing for too long. The events are worked out in a thread of their own, which stops
    at the next event once the reader has gone, and closes them, so a briefing nobody is reading stops being written
    (and paid for)."""
    q: queue.Queue[Any] = queue.Queue()
    gone = threading.Event()
    end = object()

    def work() -> None:
        try:
            for ev in events:
                q.put(ev)
                if gone.is_set():
                    break
        except Exception as exc:  # passed on, to be raised where the response is being sent
            q.put(exc)
        finally:
            close = getattr(events, "close", None)
            if close is not None:
                close()  # here, in the thread that ran it: the model's stream is closed with it
            q.put(end)

    # a new thread starts with an empty context: this one is given a copy of the caller's
    context = contextvars.copy_context()
    threading.Thread(target=context.run, args=(work,), name="sse", daemon=True).start()
    try:
        while True:
            try:
                ev = q.get(timeout=keep_alive)
            except queue.Empty:
                yield b": still working\n\n"
                continue
            if ev is end:
                return
            if isinstance(ev, Exception):
                raise ev
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n".encode()
    finally:
        gone.set()
