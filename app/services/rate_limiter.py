"""In-process sliding-window rate limiter (Phase 3A).

A single-process prototype does not need Redis or another shared store; a
small in-memory structure keyed by an arbitrary string (typically a user id)
is sufficient. State resets when the process restarts — acceptable for this
prototype's rate-limiting goal (protect the external AI provider and keep
responses snappy), not a security boundary on its own.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    """Sliding-window limiter: at most ``max_calls`` per ``window_seconds``."""

    def __init__(self) -> None:
        self._calls: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, max_calls: int, window_seconds: float = 60.0) -> bool:
        """Return True and record a call if under the limit, else False."""
        now = time.monotonic()
        q = self._calls[key]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= max_calls:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        """Clear all tracked calls (used by tests)."""
        self._calls.clear()


assistant_rate_limiter = RateLimiter()
