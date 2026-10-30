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
