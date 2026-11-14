"""Pruebas de ``app.ratelimit``: ventana deslizante por cliente con reloj fijo."""

from app.ratelimit import RateLimiter


def test_the_limit_passes_and_the_next_request_waits_a_whole_minute(clock):
    limiter = RateLimiter(limit=2, clock=clock)

    first, second, third = (limiter.check("alpha") for _ in range(3))

    assert first.allowed and second.allowed
    assert not third.allowed
    assert third.retry_after == 60
    assert isinstance(third.retry_after, int)


def test_window_slides_and_rejected_requests_do_not_count(clock):
    limiter = RateLimiter(limit=2, clock=clock)
    limiter.check("alpha")
    clock.advance(30)
    limiter.check("alpha")

    clock.advance(0.5)
    rejected = limiter.check("alpha")
    assert not rejected.allowed
    assert rejected.retry_after == 30  # ceil(0 + 60 - 30.5)

    clock.advance(29.5)  # t = 60: la primera petición ya salió de la ventana
    assert limiter.check("alpha").allowed
    assert not limiter.check("alpha").allowed

    clock.advance(30)  # t = 90: sale la de t = 30; la rechazada no cuenta
    assert limiter.check("alpha").allowed


def test_each_client_has_its_own_limit(clock):
    limiter = RateLimiter(limit=1, clock=clock)

    assert limiter.check("alpha").allowed
    assert not limiter.check("alpha").allowed
    assert limiter.check("beta").allowed
