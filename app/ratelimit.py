import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    """In-memory sliding-window limiter, per client IP. A limit of 0 disables it."""

    def __init__(self, max_requests: int, window_s: float = 60.0, clock=time.monotonic):
        self.max_requests = max_requests
        self.window_s = window_s
        self.clock = clock
        self._hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> bool:
        if self.max_requests <= 0:
            return True
        now = self.clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if not hits:
            # Drop idle keys' empty deques lazily so memory doesn't grow unbounded.
            self._hits.pop(key, None)
            hits = self._hits[key]
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True


def enforce_rate_limit(request: Request) -> None:
    limiter = request.app.state.rate_limiter
    client_ip = request.client.host if request.client else "unknown"
    if not limiter.check(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests, please slow down.")
