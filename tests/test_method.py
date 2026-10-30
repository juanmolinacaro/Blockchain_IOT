import math

from copytrading.method.backtest import LiqSnapshot, MethodConfig, Trade, find_signal, manage, run
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
    assert abs(ch.slope) < 0.02
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
    assert find_signal(cs, 60, cfg, liq + [snap(sweep_long=0.1)]) is None   # sin absorción
    t = find_signal(cs, 60, cfg, liq + [snap(sweep_long=3.0)])
    assert t is not None and t.side == "long" and t.stop < low < t.entry < t.tp1 < t.tp2
    # cierre fuera del canal: no hay recuperación -> no hay señal
    cs[-1] = candle(60, 99, 99.5, low, low + 0.01)
    assert find_signal(cs, 60, cfg, liq + [snap(sweep_long=3.0)]) is None


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
