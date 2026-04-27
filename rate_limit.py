"""
Oddiy sliding-window tezlik cheklovi (xotira ichida).
"""

from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic


class SlidingWindowLimiter:
    """Har kalit uchun `max_events` ta hodisa `window_sec` ichida."""

    def __init__(self, max_events: int, window_sec: float) -> None:
        self.max_events = max_events
        self.window_sec = window_sec
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """
        Hodisani qayd etadi.
        True — ruxsat berildi; False — limit oshib ketdi.
        """
        now = monotonic()
        q = self._events[key]
        cutoff = now - self.window_sec
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= self.max_events:
            return False
        q.append(now)
        return True


def client_ip(request, *, trust_x_forwarded_for: bool) -> str:
    """So'rov manbai (IP). Reverse proxy uchun X-Forwarded-For (ixtiyoriy)."""
    if trust_x_forwarded_for:
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()[:45]
    if request.remote:
        return request.remote
    return "unknown"
