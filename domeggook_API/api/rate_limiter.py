from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RateLimitWindow:
    max_calls: int
    period_seconds: float


class RateLimiter:
    def __init__(
        self,
        max_calls: int,
        period_seconds: float = 60.0,
        windows: list[RateLimitWindow] | None = None,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be greater than zero")
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.windows = windows or [RateLimitWindow(max_calls=max_calls, period_seconds=period_seconds)]
        for window in self.windows:
            if window.max_calls < 1:
                raise ValueError("window max_calls must be greater than zero")
            if window.period_seconds <= 0:
                raise ValueError("window period_seconds must be greater than zero")
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._calls: list[deque[float]] = [deque() for _ in self.windows]
        self._lock = Lock()

    def wait(self) -> None:
        with self._lock:
            while True:
                now = self._clock()
                sleep_for = 0.0

                for calls, window in zip(self._calls, self.windows):
                    while calls and now - calls[0] >= window.period_seconds:
                        calls.popleft()
                    if len(calls) >= window.max_calls:
                        sleep_for = max(sleep_for, window.period_seconds - (now - calls[0]))

                if sleep_for <= 0:
                    for calls in self._calls:
                        calls.append(now)
                    return

                self._sleeper(sleep_for)

