"""Pruebas de ``app.clock``: el reloj fijo para pruebas deterministas."""

from datetime import datetime, timedelta, timezone

from app.clock import FixedClock

START = datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc)


def test_fixed_clock_is_utc_and_only_moves_when_asked():
    clock = FixedClock(START)
    first_tick = clock.monotonic()

    assert clock.now() == START
    assert clock.now().utcoffset() == timedelta(0)
    assert clock.monotonic() == first_tick

    clock.advance(1.5)

    assert clock.now() == START + timedelta(seconds=1.5)
    assert clock.monotonic() == first_tick + 1.5
