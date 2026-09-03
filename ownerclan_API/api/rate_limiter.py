from __future__ import annotations

import time
from threading import Lock


class RateLimiter:
    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = max(float(interval_seconds), 0.0)
        self._last_request_at = 0.0
        self._lock = Lock()

    def wait(self) -> None:
        if self.interval_seconds <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = self.interval_seconds - (now - self._last_request_at)
            if delay > 0:
                time.sleep(delay)
            self._last_request_at = time.monotonic()

