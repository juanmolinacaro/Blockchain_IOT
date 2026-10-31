from copytrading.method.traps import find_breakouts
from copytrading.models import Candle

H = 3_600_000


def c(i, o, h, l, cl, v=1.0):
    return Candle(i * H, o, h, l, cl, v)


def flat(n):
    return [c(i, 100, 101, 99, 100) for i in range(n)]


def test_false_breakout_is_a_trap_and_reaches_other_side():
    cs = flat(24) + [c(24, 100, 101.5, 100, 101.2, v=0.5)]          # rompe 101 apenas y con poco volumen
    cs += [c(25, 101, 101, 99.5, 100.2), c(26, 100, 100, 98.5, 98.8)]  # vuelve dentro y baja al otro extremo
    cs += flat(30)
    b = find_breakouts(cs, lookback=24, hold=6, after=24)[0]
    assert b.up and b.trap and b.reached_opposite and b.vol_ratio == 0.5


def test_real_breakout_holds_and_follows_through():
    cs = flat(24) + [c(24, 100, 103, 100, 102.9, v=3)]
    cs += [c(25 + k, 103 + k, 104 + k, 102.5 + k, 103.5 + k) for k in range(30)]
    b = find_breakouts(cs, lookback=24, hold=6, after=24)[0]
    assert not b.trap and b.follow > 0.1 and b.wick < 0.05 and b.excess > 0.01
