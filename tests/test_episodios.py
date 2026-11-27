from datetime import datetime, timedelta

from copytrading.episodios import COT, detect

T0 = datetime(2026, 11, 9, 12, 0, tzinfo=COT)


def _s(prices):
    return [(T0 + timedelta(minutes=i), p) for i, p in enumerate(prices)]


def test_squeeze_then_break_up_and_strong_moves():
    flat = [75000 + (i % 3) * 20 for i in range(90)]               # 90 min apretado
    up = [75060 + 40 * k for k in range(1, 20)]                    # rompe arriba > 0,7 %
    got = [t for t, *_ in detect(_s(flat + up))]
    assert "compresión→arriba" in got


def test_rebound_after_crash_is_labelled():
    down = [76000 - 30 * k for k in range(40)]                     # −1,5 %
    up = [74830 + 30 * k for k in range(1, 40)]                    # +1,5 % justo después
    got = [t for t, *_ in detect(_s([76000] * 5 + down + up))]
    assert got[:2] == ["caída fuerte", "rebote tras caída"]
