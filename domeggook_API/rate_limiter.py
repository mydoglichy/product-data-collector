from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        max_calls: int,
        period_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be greater than zero")
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._calls: deque[float] = deque()

    def wait(self) -> None:
        now = self._clock()
        while self._calls and now - self._calls[0] >= self.period_seconds:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            sleep_for = self.period_seconds - (now - self._calls[0])
            if sleep_for > 0:
                self._sleeper(sleep_for)
            now = self._clock()
            while self._calls and now - self._calls[0] >= self.period_seconds:
                self._calls.popleft()
        self._calls.append(now)

