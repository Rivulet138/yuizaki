"""Simple in-memory sliding-window rate limiter."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after: float
    remaining: int


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max(1, int(max_requests))
        self.window_seconds = max(0.1, float(window_seconds))
        self._events: dict[str, deque[float]] = {}

    def check(self, key: str) -> RateLimitResult:
        now = time.time()
        events = self._events.setdefault(key, deque())
        cutoff = now - self.window_seconds

        while events and events[0] < cutoff:
            events.popleft()

        # 清理空 key，防止无限增长
        if not events and key in self._events:
            del self._events[key]
            events = self._events.setdefault(key, deque())

        if len(events) >= self.max_requests:
            retry_after = max(0.01, self.window_seconds - (now - events[0]))
            return RateLimitResult(
                allowed=False,
                retry_after=retry_after,
                remaining=0,
            )

        events.append(now)
        remaining = max(0, self.max_requests - len(events))
        return RateLimitResult(
            allowed=True,
            retry_after=0.0,
            remaining=remaining,
        )
