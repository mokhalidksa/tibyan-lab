"""A per-IP sliding-window rate limit, held in memory. Nothing about a request is stored except its time."""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict, deque


class RateLimiter:
    def __init__(self, requests: int, window_seconds: int, max_clients: int = 10_000) -> None:
        self.requests = requests
        self.window = window_seconds
        self.max_clients = max_clients
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, client: str, now: float | None = None) -> int | None:
        """Record a request. Returns None if allowed, or the seconds to wait if not."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.pop(client, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.requests:
                self._hits[client] = hits
                return max(1, math.ceil(self.window - (now - hits[0])))
            hits.append(now)
            self._hits[client] = hits
            while len(self._hits) > self.max_clients:
                self._hits.popitem(last=False)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_ip(forwarded_for: str | None, peer: str | None, trusted_hops: int) -> str:
    """The client address, taken from X-Forwarded-For only as far as the trusted proxies vouch for it."""
    if forwarded_for and trusted_hops > 0:
        chain = [part.strip() for part in forwarded_for.split(",") if part.strip()]
        if len(chain) >= trusted_hops:
            return chain[-trusted_hops]
    return peer or "unknown"


class DailyLimit:
    """Counts per client and in total for the current UTC day; resets at midnight UTC."""

    def __init__(self, per_client: int, total: int) -> None:
        self.per_client = per_client
        self.total = total
        self._day = ""
        self._counts: dict[str, int] = {}
        self._all = 0
        self._lock = threading.Lock()

    def check(self, client: str, day: str) -> int | None:
        """Record one use. None if allowed, else seconds until the limit resets."""
        with self._lock:
            if day != self._day:
                self._day, self._counts, self._all = day, {}, 0
            if self._all >= self.total or self._counts.get(client, 0) >= self.per_client:
                now = time.gmtime()
                return max(1, 86400 - (now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec))
            self._counts[client] = self._counts.get(client, 0) + 1
            self._all += 1
            return None
