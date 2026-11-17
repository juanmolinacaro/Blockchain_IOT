from copytrading.method.shortliq import describe, short_term_zones
from copytrading.models import Candle


def _flat(n=72, px=100.0, vol=1000.0):
    return [Candle(i * 3_600_000, px, px * 1.001, px * 0.999, px, vol) for i in range(n)]


def test_zones_sit_at_high_leverage_liquidation_prices():
    longs, shorts = short_term_zones(_flat())
    assert longs and shorts
    assert all(z.center < 100 for z in longs) and all(z.center > 100 for z in shorts)
    # 100x / 50x / 25x quedan a ~0,6 %, ~1,6 % y ~3,6 % del precio
    assert any(abs(z.center / 100 - 1) < 0.02 for z in longs + shorts)


def test_old_liquidity_fades_with_short_half_life():
    old = [Candle(i * 3_600_000, 120.0, 120.1, 119.9, 120.0, 1e6) for i in range(10)]
    recent = [Candle((10 + i) * 3_600_000, 100.0, 100.1, 99.9, 100.0, 1000.0) for i in range(200)]
    longs, shorts = short_term_zones(old + recent, rng=0.25)
    assert all(z.center < 110 for z in shorts)   # los cortos viejos de 120 ya no pesan


def test_describe_flags_two_x_imbalance():
    from copytrading.method.shortliq import STZone
    lines = describe([STZone("long", 95, 300)], [STZone("short", 105, 100)])
    assert any("imán abajo" in ln for ln in lines)
