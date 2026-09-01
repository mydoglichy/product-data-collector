from domeggook_API.api.rate_limiter import RateLimiter, RateLimitWindow


def test_rate_limiter_respects_the_most_constrained_window():
    now = 0.0
    sleeps = []

    def clock():
        return now

    def sleeper(seconds):
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    limiter = RateLimiter(
        max_calls=2,
        windows=[
            RateLimitWindow(max_calls=2, period_seconds=60.0),
            RateLimitWindow(max_calls=3, period_seconds=3600.0),
            RateLimitWindow(max_calls=4, period_seconds=86400.0),
        ],
        clock=clock,
        sleeper=sleeper,
    )

    limiter.wait()
    limiter.wait()
    limiter.wait()
    limiter.wait()
    limiter.wait()

    assert sleeps == [60.0, 3540.0, 82800.0]
