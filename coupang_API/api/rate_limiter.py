from __future__ import annotations

from collections.abc import Callable

from rate_limiter import WindowRateLimiter


class RateLimiter(WindowRateLimiter):
    def __init__(
        self,
        max_calls: int = 45,
        period_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__(
            max_calls=max_calls,
            period_seconds=period_seconds,
            clock=clock,
            sleeper=sleeper,
        )
