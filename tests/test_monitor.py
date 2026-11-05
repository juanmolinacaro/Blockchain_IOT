import pytest

from copytrading.method.backtest import Trade
from copytrading.method.monitor import (
    CoinStatus,
    closed_candles,
    load_journal,
    manual_entry,
    record_signals,
    save_journal,
    summary,
    update_outcome,
)
from copytrading.models import Candle

H4 = 14_400_000


def c(i, o, h, l, cl):
    return Candle(i * H4, o, h, l, cl, 1.0)


def test_closed_candles_drops_the_running_one():
    cs = [c(0, 1, 1, 1, 1), c(1, 1, 1, 1, 1), c(2, 1, 1, 1, 1)]
    assert len(closed_candles(cs, "4h", now_ms=2 * H4 + 1000)) == 2
    assert len(closed_candles(cs, "4h", now_ms=3 * H4)) == 3


def test_record_signals_is_idempotent():
    st = CoinStatus("BTC", 5 * H4, 100.0, "SEÑAL", {"sistema-A": Trade("long", 5, 100, 98, 102, 104)})
    entries = []
    assert len(record_signals(entries, st, "4h")) == 1
    assert record_signals(entries, st, "4h") == []
    assert entries[0].id == f"sistema-A-BTC-{5 * H4}"


def test_update_outcome_open_then_closed():
    e = manual_entry("BTC", "long", 100, 98, 102, 104, now_ms=0)
    cs = [c(0, 100, 100, 100, 100), c(1, 100, 101, 99.5, 100.5)]
    update_outcome(e, cs)
    assert e.status == "abierta" and e.r > 0           # sigue viva, con resultado latente
    cs += [c(2, 100.5, 102.5, 100, 102), c(3, 102, 104.5, 102, 104)]
    update_outcome(e, cs)
    assert e.status == "cerrada" and e.exit_reason == "tp2" and e.exit_time == 3 * H4
    assert e.r > 1.4


def test_manual_entry_validates_levels():
    with pytest.raises(ValueError):
        manual_entry("BTC", "long", 100, 101, 102, 104)
    with pytest.raises(ValueError):
        manual_entry("BTC", "short", 100, 99, 98, 97)


def test_journal_roundtrip_and_summary(tmp_path):
    path = tmp_path / "d.jsonl"
    a = manual_entry("BTC", "long", 100, 98, 102, 104, now_ms=1)
    a.status, a.r = "cerrada", 1.5
    b = manual_entry("ETH", "short", 100, 102, 98, 96, now_ms=2)
    save_journal(path, [a, b])
    loaded = load_journal(path)
    assert [e.coin for e in loaded] == ["BTC", "ETH"]
    line = summary(loaded)[0]
    assert "cerradas   1" in line and "abiertas 1" in line and "+1.50R" in line


# --------------------------------------------------------- planes condicionados
from copytrading.method.monitor import manual_plan  # noqa: E402

H1 = 3_600_000


def c1(i, o, h, l, cl):
    return Candle(i * H1, o, h, l, cl, 1.0)


def short_plan(hours=48):
    return manual_plan("ETH", "short", 2223, "below", 2265, 2175, 2137, hours=hours, now_ms=0)


def test_plan_stays_pending_until_close_beyond_trigger():
    e = short_plan()
    cs = [c1(0, 2230, 2240, 2220, 2228), c1(1, 2228, 2236, 2215, 2226)]   # mechas por debajo, cierres por encima
    update_outcome(e, cs)
    assert e.status == "pendiente"


def test_plan_activates_on_close_and_then_hits_targets():
    e = short_plan()
    cs = [c1(0, 2230, 2240, 2220, 2228), c1(1, 2226, 2230, 2210, 2215),     # cierra por debajo: se activa
          c1(2, 2215, 2220, 2170, 2172), c1(3, 2172, 2175, 2130, 2135)]
    update_outcome(e, cs)
    assert e.entry == 2215 and e.time == 1 * H1
    assert e.status == "cerrada" and e.exit_reason == "tp2" and e.r > 1


def test_plan_expires():
    e = short_plan(hours=2)
    cs = [c1(k, 2230, 2240, 2225, 2230) for k in range(5)]
    update_outcome(e, cs)
    assert e.status == "caducada"


def test_plan_annulled_if_activation_close_beyond_target():
    e = short_plan()
    update_outcome(e, [c1(0, 2230, 2232, 2160, 2165)])     # cierra ya por debajo del TP1
    assert e.status == "anulada"


def test_long_plan_validation():
    with pytest.raises(ValueError):
        manual_plan("ETH", "long", 2242, "above", 2250, 2280, 2317)
    p = manual_plan("ETH", "long", 2242, "above", 2190, 2280, 2317, now_ms=0)
    assert p.status == "pendiente" and p.interval == "1h"


def test_limit_plan_fills_on_touch_at_trigger_price():
    e = manual_plan("BTC", "long", 77500, "touch_below", 76400, 79150, 80200, now_ms=0)
    cs = [c1(0, 78100, 78300, 77800, 78000), c1(1, 78000, 78050, 77450, 77700),   # toca 77.500
          c1(2, 77700, 79300, 77600, 79200), c1(3, 79200, 80300, 79000, 80250)]
    update_outcome(e, cs)
    assert e.entry == 77500 and e.time == 1 * H1
    assert e.status == "cerrada" and e.exit_reason == "tp2"


def test_limit_plan_annulled_if_price_runs_without_pullback():
    e = manual_plan("BTC", "long", 77500, "touch_below", 76400, 79150, 80200, now_ms=0)
    update_outcome(e, [c1(0, 78100, 78600, 77900, 78500), c1(1, 78500, 79200, 78400, 79100)])
    assert e.status == "anulada" and "sin retroceder" in e.exit_reason


def test_weekend_rule_colombia_time():
    from datetime import datetime, timezone

    from copytrading.method.monitor import trading_allowed
    ms = lambda y, mo, d, h: int(datetime(y, mo, d, h, tzinfo=timezone.utc).timestamp() * 1000)
    assert trading_allowed(ms(2026, 10, 29, 20))          # jueves
    assert not trading_allowed(ms(2026, 10, 30, 12))      # viernes 7 h Colombia
    assert not trading_allowed(ms(2026, 10, 31, 20))      # sábado
    assert not trading_allowed(ms(2026, 11, 1, 17))       # domingo 12 h Colombia
    assert trading_allowed(ms(2026, 11, 1, 18))           # domingo 13 h Colombia
    assert trading_allowed(ms(2026, 11, 2, 3))            # domingo 22 h Colombia


def test_hourly_plans_get_five_days_before_time_exit():
    e = manual_entry("BTC", "long", 100, 90, 120, 130, interval="1h", now_ms=0)
    cs = [c1(k, 100, 101, 99, 100) for k in range(60)]      # 60 h sin tocar stop ni objetivos
    update_outcome(e, cs)
    assert e.status == "abierta"                              # antes se cerraba "por tiempo" a las 30 h


def test_manual_plan_4h_counts_from_current_candle():
    from copytrading.method.monitor import manual_plan
    now = 1_793_648_010_684                     # lun 2 nov 2026 19:33 UTC
    e = manual_plan("BTC", "short", 77250, "below", 78100, 76470, 74800, interval="4h", now_ms=now)
    assert e.interval == "4h"
    assert e.time == 1_793_635_200_000          # vela de 4H que abrió a las 16:00 UTC


def test_sweep_plan_needs_the_sweep_before_the_close_back_inside():
    from copytrading.method.monitor import activate_plan, manual_plan
    from copytrading.models import Candle
    h = 3_600_000
    e = manual_plan("BTC", "short", 78000, "below", 78900, 76300, 75500, sweep=78150, now_ms=0)
    candles = [Candle(0, 77900, 77950, 77800, 77850, 1),        # cierra < 78.000 pero sin barrido: nada
               Candle(h, 77850, 78300, 77850, 78200, 1),        # barre 78.150
               Candle(2 * h, 78200, 78250, 77700, 77750, 1)]    # vuelve a cerrar dentro: se activa
    activate_plan(e, candles)
    assert e.status == "abierta" and e.entry == 77750 and e.time == 2 * h


def test_pending_plan_is_cancelled_when_price_closes_beyond_its_stop():
    from copytrading.method.monitor import activate_plan, manual_plan
    from copytrading.models import Candle
    h = 3_600_000
    e = manual_plan("BTC", "short", 78000, "below", 78900, 76300, 75500, sweep=78150, now_ms=0)
    candles = [Candle(0, 78100, 78400, 78000, 78300, 1), Candle(h, 78300, 79500, 78200, 79400, 1),
               Candle(2 * h, 79400, 79400, 77500, 77600, 1)]
    activate_plan(e, candles)
    assert e.status == "anulada" and "invalidado" in e.exit_reason


def test_runner_secures_half_and_trails():
    from copytrading.method.backtest import MethodConfig, Trade, manage
    from copytrading.models import Candle
    h = 3_600_000
    # corto en 100: TP1 98 (mitad), luego cae a 90 y rebota; el stop móvil (máximo de 3 velas) lo saca en 92,6
    path = [(100, 100.5, 99.5, 100), (100, 100.2, 97.8, 98), (98, 98.2, 95, 95.5), (95.5, 95.6, 92, 92.5),
            (92.5, 92.6, 90, 90.5), (90.5, 91, 90, 90.8), (90.8, 91, 90.2, 90.9), (90.9, 94, 90.8, 93.8)]
    candles = [Candle(i * h, o, hi, lo, c, 1) for i, (o, hi, lo, c) in enumerate(path)]
    cfg = MethodConfig(trail_bars=3, fee=0.0, slippage=0.0, stop_buffer=0.0)
    t = manage(Trade("short", 0, 100.0, 102.0, 98.0, 0.0), candles, cfg)
    assert t.exit_reason == "stop móvil"
    assert abs(t.r - (0.5 * (100 - 98) / 2 + 0.5 * (100 - 92.6) / 2)) < 1e-9   # la mitad corrió hasta 92,6
