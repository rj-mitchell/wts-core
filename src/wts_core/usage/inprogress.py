"""Briefings being written right now.

Their cost is only known when they finish, so without this, many requests at once would all pass the spending
caps before any was counted: each is reserved at an estimated cost while it runs, and each visitor (and the site as
a whole) may have only a few at once. In memory, for one process.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from wts_core.ports import Busy, InProgress

__all__ = ["BriefingsInProgress"]


class BriefingsInProgress:
    """Places for briefings in progress (``ports.InProgress``): ``per_key`` for one visitor, ``total`` for the
    site, each counted at ``estimate_usd`` against the caps. The three figures are the site's own (2 and 8 on every
    site today; $0.15 on Where MPs Stand and Where Councils Stand, $0.10 on Where Countries Stand)."""

    def __init__(self, per_key: int, total: int, estimate_usd: float) -> None:
        self.per_key, self.total, self.estimate_usd = per_key, total, estimate_usd
        self._running: dict[str, int] = {}
        self._lock = threading.Lock()

    @property
    def running(self) -> dict[str, int]:
        """How many briefings each key has in progress now (a copy)."""
        with self._lock:
            return dict(self._running)

    def start(self, key: str) -> Busy | None:
        """Reserve a place, or say why not. A refused visitor leaves nothing behind."""
        with self._lock:
            if self._running.get(key, 0) >= self.per_key:
                return Busy("visitor")
            if sum(self._running.values()) >= self.total:
                return Busy("site")
            self._running[key] = self._running.get(key, 0) + 1
            return None

    def finish(self, key: str) -> None:
        with self._lock:
            left = self._running.get(key, 0) - 1
            if left <= 0:
                self._running.pop(key, None)
            else:
                self._running[key] = left

    def pending_usd(self, besides: int = 0) -> float:
        """Estimated cost of the briefings in progress, not counting ``besides`` of them (the caller's own)."""
        with self._lock:
            return max(sum(self._running.values()) - besides, 0) * self.estimate_usd

if TYPE_CHECKING:  # checked by mypy: the class is what its interface asks for

    def _as_inprogress(x: BriefingsInProgress) -> InProgress:
        return x
