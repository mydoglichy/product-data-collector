from coupang_API.api.rate_limiter import RateLimiter


def test_rate_limiter_keeps_calls_within_period():
    now = 0.0
    sleeps = []

    def clock():
        return now

    def sleeper(seconds):
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    limiter = RateLimiter(max_calls=2, period_seconds=60.0, clock=clock, sleeper=sleeper)

    limiter.wait()
    limiter.wait()
    limiter.wait()

    assert sleeps == [60.0]

