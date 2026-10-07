from app.ratelimit import RateLimiter


def test_allows_up_to_limit_then_blocks():
    limiter = RateLimiter(3, clock=lambda: 0.0)
    assert [limiter.check("a") for _ in range(4)] == [True, True, True, False]


def test_limits_are_per_key():
    limiter = RateLimiter(1, clock=lambda: 0.0)
    assert limiter.check("a") is True
    assert limiter.check("b") is True
    assert limiter.check("a") is False


def test_window_expires():
    now = [0.0]
    limiter = RateLimiter(1, window_s=60, clock=lambda: now[0])
    assert limiter.check("a") is True
    assert limiter.check("a") is False
    now[0] = 61.0
    assert limiter.check("a") is True


def test_zero_disables_limiting():
    limiter = RateLimiter(0)
    assert all(limiter.check("a") for _ in range(1000))
