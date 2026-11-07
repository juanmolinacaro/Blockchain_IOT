from copytrading.method.liqmodel import LiquidationModel
from copytrading.method.pools import StudyConfig, _first_touch, _zones, config_for, study
from copytrading.models import Candle

H = 3_600_000


def c(i, o, h, l, cl, v=1.0):
    return Candle(i * H, o, h, l, cl, v)


def test_zones_find_peaks_not_one_big_block():
    m = LiquidationModel()
    px = 100.0
    for k in range(-30, 0):                       # liquidez repartida por debajo del precio...
        m.longs[m._bin(px * (1 + k * 0.0025))] = 1.0
    peak = m._bin(95.0)
    m.longs[peak] = 40.0                          # ...y un pico claro en 95
    zs = _zones(m, "long", px, avg=1.0, cfg=StudyConfig(min_size=5))
    assert len(zs) == 1
    z = zs[0]
    assert z.lo_bin <= peak <= z.hi_bin and z.hi_bin - z.lo_bin <= 6
    assert 94.5 < z.center < 95.5


def test_mean_time_is_usd_weighted():
    m = LiquidationModel(leverage_weights={10: 1.0})
    m.update(c(0, 100, 100, 100, 100, v=1))
    m.update(c(10, 100, 100, 100, 100, v=3))     # mismo nivel, 3x más volumen 10 h después
    b = m._bin(100 * (1 - 0.1 + 0.004))
    assert abs(m.mean_time("long", [b]) - 7.5 * H) < 1


def test_first_touch():
    cs = [c(0, 100, 100, 100, 100), c(1, 100, 101, 99, 100), c(2, 100, 106, 99, 105)]
    assert _first_touch(cs, 0, 95, 105, 5) == "arriba"
    assert _first_touch(cs, 0, 95, 110, 5) == "ninguno"


def test_config_scales_to_real_hours():
    one, four = config_for(1), config_for(4)
    assert one.horizons == (8, 24, 72) and four.horizons == (2, 6, 18)
    assert four.trap_window == 12 and abs(four.half_life_bars - 84) < 1e-9


def test_study_detects_pool_and_its_sweep():
    # rango lateral que carga longs alrededor de 90.4 (10x desde 100) y luego un barrido hasta 89
    cs = [c(i, 100, 100.3, 99.7, 100, v=10) for i in range(200)]
    cs += [c(200, 100, 100, 92, 93), c(201, 93, 93, 89, 92), c(202, 92, 96, 91.5, 95.5)]
    cs += [c(203 + k, 95.5, 96, 95, 95.5) for k in range(80)]
    res = study(cs, StudyConfig(min_size=5, horizons=(1, 24), forward=24))
    swept = [p for p in res.pools if p.end == "liquidado" and p.side == "long"]
    assert swept, [(p.side, p.center, p.end) for p in res.pools]
    p = swept[0]
    assert p.swept_i == 201 and p.reclaimed and p.bounce[24] > 0.04
