import math

from copytrading.method.backtest import (
    LiqSnapshot,
    MethodConfig,
    Trade,
    compute_channels,
    find_signal,
    manage,
    run,
)
from copytrading.method.channels import regression_channel
from copytrading.method.liqmodel import LiquidationModel
from copytrading.models import Candle

H = 14_400_000


def candle(i, o, h, l, c, v=100.0):
    return Candle(i * H, o, h, l, c, v)


def flat_channel(n=60, px=100.0, amp=2.0):
    """Precio oscilando en un canal horizontal 98–102."""
    out = []
    for i in range(n):
        mid = px + amp * math.sin(i / 3)
        out.append(candle(i, mid, mid + 0.5, mid - 0.5, mid))
    return out


def test_regression_channel_flat():
    cs = flat_channel()
    ch = regression_channel(cs, len(cs), 60)
    assert abs(ch.slope) < 0.02 and ch.up_slope == ch.lo_slope
    assert 101 < ch.upper(60) < 103 and 97 < ch.lower(60) < 99
    assert regression_channel(cs, 10, 60) is None   # no hay suficientes velas


def test_liquidation_model_sweeps_levels():
    m = LiquidationModel(leverage_weights={10: 1.0})
    m.update(candle(0, 100, 100, 100, 100, v=10))     # longs a ~90.4, shorts a ~109.6
    assert m.zones("long")[0][0] < 91 and m.zones("short")[0][0] > 109
    sl, ss = m.update(candle(1, 100, 101, 89, 95, v=0))   # baja a 89: barre los longs
    assert sl > 900 and ss == 0
    assert not m.longs
    sl, ss = m.update(candle(2, 95, 111, 95, 110, v=0))   # sube a 111: barre los shorts
    assert ss > 900


def snap(**kw):
    base = dict(sweep_long=0.0, sweep_short=0.0, long_below=0.0, short_above=0.0,
                best_long_px=0.0, best_short_px=0.0)
    base.update(kw)
    return LiqSnapshot(**base)


def test_long_signal_needs_touch_absorption_and_reclaim():
    cs = flat_channel()
    ch = regression_channel(cs, 60, 60)
    low = ch.lower(60) - 0.5
    cs.append(candle(60, 99, 99.5, low, 99.2))          # perfora el borde inferior y cierra dentro
    cfg = MethodConfig(lookback=60, min_rr=0.5)
    liq = [snap()] * 60
    chs = compute_channels(cs, cfg)
    emas = [[] for _ in cs]
    assert find_signal(cs, 60, cfg, liq + [snap(sweep_long=0.1)], chs, emas) is None   # sin absorción
    t = find_signal(cs, 60, cfg, liq + [snap(sweep_long=3.0)], chs, emas)
    assert t is not None and t.side == "long" and t.stop < low < t.entry < t.tp1 < t.tp2
    # cierre fuera del canal: no hay recuperación -> no hay señal
    cs[-1] = candle(60, 99, 99.5, low, low + 0.01)
    assert find_signal(cs, 60, cfg, liq + [snap(sweep_long=3.0)], compute_channels(cs, cfg), emas) is None


def test_manage_partial_then_breakeven():
    cfg = MethodConfig(fee=0, slippage=0)
    cs = [candle(0, 100, 100, 100, 100), candle(1, 100, 103, 100, 102), candle(2, 102, 102, 99, 99)]
    t = manage(Trade("long", 0, 100, 98, 102, 106), cs, cfg)
    # mitad en TP1 (+1R) y la otra mitad a breakeven (0R)
    assert t.exit_reason == "breakeven" and abs(t.r - 0.5) < 1e-9


def test_close_stop_ignores_wick_but_respects_hard_stop():
    cs = [candle(0, 100, 100, 100, 100), candle(1, 100, 100, 97.5, 99.5), candle(2, 99.5, 99.5, 95, 95.5)]
    wick = manage(Trade("long", 0, 100, 98, 102, 106), cs, MethodConfig(fee=0, slippage=0, stop_mode="wick"))
    assert wick.exit_i == 1 and abs(wick.r + 1) < 1e-9
    close = manage(Trade("long", 0, 100, 98, 102, 106), cs,
                   MethodConfig(fee=0, slippage=0, stop_mode="close", hard_stop_r=2.0))
    assert close.exit_i == 2 and abs(close.r + 2) < 1e-9          # la mecha de la vela 1 no lo saca


def test_run_compounds_and_never_overlaps():
    cs = flat_channel(400)
    res = run(cs, MethodConfig(use_liquidity=False, min_rr=0.3))
    assert res.n > 0 and len(res.equity) == res.n + 1
    for a, b in zip(res.trades, res.trades[1:]):
        assert b.entry_i > a.exit_i


# ------------------------------------------------------------- pivotes y EMAs
from copytrading.method.channels import find_pivots, pivot_channels  # noqa: E402
from copytrading.method.emas import ema_series, parse_spec  # noqa: E402

D = 86_400_000


def zigzag(n=120, period=20, base=100.0, amp=5.0, drift=0.0):
    """Ondas triangulares: máximos y mínimos claros cada period/2 velas."""
    out = []
    for i in range(n):
        phase = (i % period) / period
        tri = 4 * phase - 1 if phase < 0.5 else 3 - 4 * phase   # -1 -> 1 -> -1
        mid = base + drift * i + amp * tri
        out.append(candle(i, mid, mid + 0.2, mid - 0.2, mid))
    return out


def test_find_pivots_on_zigzag():
    highs, lows = find_pivots(zigzag(), k=3)
    assert highs[:3] == [10, 30, 50] and lows[:3] == [20, 40, 60]


def test_pivot_channel_uses_only_confirmed_pivots_and_follows_trend():
    cs = zigzag(drift=0.05)
    chs = pivot_channels(cs, k=3, max_age=200, min_gap=5)
    assert all(ch is None for ch in chs[:34])      # hacen falta 2 máximos y 2 mínimos confirmados
    ch = chs[100]
    assert ch is not None and ch.shape() == "alcista"
    assert abs(ch.up_slope - 0.05) < 1e-9 and abs(ch.lo_slope - 0.05) < 1e-9
    # no mira el futuro: cambiar velas posteriores a j no altera el canal en j
    altered = cs[:101] + [candle(i, 500, 500, 500, 500) for i in range(101, 120)]
    assert pivot_channels(altered, k=3, max_age=200, min_gap=5)[100] == ch


def test_pivot_channel_detects_triangle_and_broken_lines():
    # máximos decrecientes y mínimos crecientes -> triángulo
    cs = []
    for i in range(80):
        amp = 8 - i * 0.08
        phase = (i % 20) / 20
        tri = 4 * phase - 1 if phase < 0.5 else 3 - 4 * phase
        mid = 100 + amp * tri
        cs.append(candle(i, mid, mid + 0.1, mid - 0.1, mid))
    chs = pivot_channels(cs, k=3, max_age=200, min_gap=5)
    assert chs[70].shape() == "triángulo"
    # un cierre muy por debajo de la línea inferior la rompe
    broken = cs[:65] + [candle(65, 80, 80, 80, 80)] + cs[66:]
    assert pivot_channels(broken, k=3, max_age=200, min_gap=5)[70] is None


def test_daily_ema_has_no_lookahead():
    # 4H: 6 velas por día. Día 0 a 100, día 1 a 200.
    cs = [Candle(i * H, 0, 0, 0, 100.0 if i < 6 else 200.0, 1) for i in range(18)]
    e = ema_series(cs, "1d", 1)
    assert e[:6] == [None] * 6                 # el día 0 aún no ha cerrado
    assert e[6:12] == [100.0] * 6              # durante el día 1 se usa el cierre del día 0
    assert e[12] == 200.0
    assert parse_spec("1d:200, 4h:50") == [("1d", 200), ("4h", 50)]


def test_ema_confluence_required():
    cs = flat_channel()
    cfg = MethodConfig(lookback=60, min_rr=0.5, ema="1d:1", ema_mode="confluence")
    ch = regression_channel(cs, 60, 60)
    low = ch.lower(60) - 0.5
    cs.append(candle(60, 99, 99.5, low, 99.2))
    chs = compute_channels(cs, cfg)
    liq = [snap()] * 60 + [snap(sweep_long=3.0)]
    emas_far = [[] for _ in cs[:-1]] + [[120.0]]
    emas_near = [[] for _ in cs[:-1]] + [[low]]
    assert find_signal(cs, 60, cfg, liq, chs, emas_far) is None
    assert find_signal(cs, 60, cfg, liq, chs, emas_near) is not None
