from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    """
    Sliding-window per-chat rate limiter.

    Thread-safe for asyncio (single-threaded event loop); not safe for multi-process.
    """

    def __init__(self, max_per_minute: int = 20) -> None:
        self._max = max_per_minute
        self._windows: dict[int, deque[float]] = defaultdict(deque)

    def is_allowed(self, chat_id: int) -> bool:
        if self._max <= 0:
            return True

        now = time.monotonic()
        window = self._windows[chat_id]

        # Drop timestamps older than 60 seconds.
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) >= self._max:
            return False

        window.append(now)
        return True


# Module-level singleton; max_per_minute is patched in app.main after settings load.
rate_limiter = RateLimiter()
