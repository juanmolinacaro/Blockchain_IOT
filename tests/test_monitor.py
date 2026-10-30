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
