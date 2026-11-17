"""The per-minute limit on requests: Where MPs Stand's limiter, which every site now has.

In memory and for one process: nothing is written down. A lock makes it safe to call from several threads at once
(Where Landlords Stand's first copy had none), and once more than ``forget_over`` keys are held, those with nothing
in the last minute are forgotten, so the memory used stays small.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import TYPE_CHECKING

from wts_core.ports import SYSTEM_CLOCK, Clock, Limiter

__all__ = ["RateLimiter"]

WINDOW = 60.0  # seconds; an entry exactly this old still counts


class RateLimiter:
    """At most ``per_minute`` requests per key in any rolling minute (``ports.Limiter``).

    ``forget_over`` is the number of keys held beyond which idle ones are forgotten: 50,000 on Where MPs Stand,
    Where Countries Stand and Where Landlords Stand, 10,000 on Where Councils Stand. The key is whatever the site
    counts by (a visitor's code, ``user:<id>``); the package never sees an address here.
    """

    def __init__(self, per_minute: int, *, forget_over: int, clock: Clock = SYSTEM_CLOCK) -> None:
        self.per_minute = per_minute
        self.forget_over = forget_over
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > WINDOW:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            if len(self._hits) > self.forget_over:  # forget idle visitors
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] > WINDOW]:
                    del self._hits[k]
            return True

if TYPE_CHECKING:  # checked by mypy: the class is what its interface asks for

    def _as_limiter(x: RateLimiter) -> Limiter:
        return x
