from datetime import datetime, timedelta

from copytrading.causa import COT, bolsa_abierta, classify, episodes, find_moves, read_series
from copytrading.nasdaq_escucha import parse_chart


def _series(start: datetime, prices: list[float]):
    return [(start + timedelta(minutes=i), p) for i, p in enumerate(prices)]


T0 = datetime(2026, 11, 5, 9, 0, tzinfo=COT)


def test_find_moves_detects_drop_from_the_high():
    prices = [100.0] * 10 + [100.5] + [100.5 - 0.1 * k for k in range(1, 26)] + [98.0] * 10
    moves = find_moves(_series(T0, prices), umbral=0.015, ventana=60)
    assert len(moves) == 1
    i, j = moves[0]
    assert prices[i] == 100.5 and prices[j] == min(prices)


def test_find_moves_ignores_small_moves():
    prices = [100 + (0.3 if k % 2 else 0) for k in range(120)]
    assert find_moves(_series(T0, prices)) == []


def test_classify():
    assert classify(-0.005, -0.002, down=True) == "la bolsa se movió primero"
    assert classify(0.0, -0.006, down=True) == "a la vez"
    assert classify(0.001, 0.0, down=True) == "solo cripto"
    assert classify(None, None, down=True) == "bolsa sin datos"
    assert classify(0.004, 0.0, down=False) == "la bolsa se movió primero"


def test_episodes_with_nasdaq_falling_first():
    btc_prices = [100.0] * 40 + [100 - 0.1 * k for k in range(1, 31)] + [97.0] * 10
    btc = _series(T0, btc_prices)
    nq_prices = [20000 - 4 * k for k in range(80)]            # el Nasdaq ya caía antes
    nq = _series(T0, nq_prices)
    eps = episodes(btc, nq)
    assert len(eps) == 1
    e = eps[0]
    assert e.btc_cambio < -0.015
    assert e.causa == "la bolsa se movió primero"
    assert not e.inicio_sin_grabar


def test_episode_right_after_a_gap_is_flagged():
    first = _series(T0, [100.0] * 5)
    later = _series(T0 + timedelta(hours=3), [100 - 0.1 * k for k in range(31)])
    assert episodes(first + later, [])[0].inicio_sin_grabar


def test_episodes_without_nasdaq_data():
    btc = _series(T0, [100.0] * 40 + [100 - 0.1 * k for k in range(1, 31)])
    assert episodes(btc, [])[0].causa == "bolsa sin datos"


def test_bolsa_abierta_respects_new_york_time():
    assert bolsa_abierta(datetime(2026, 11, 5, 9, 51, tzinfo=COT))        # invierno: NY = Colombia
    assert not bolsa_abierta(datetime(2026, 11, 5, 18, 0, tzinfo=COT))
    assert bolsa_abierta(datetime(2026, 7, 7, 8, 45, tzinfo=COT))         # verano: abre 8:30 en Colombia
    assert not bolsa_abierta(datetime(2026, 11, 7, 10, 0, tzinfo=COT))    # sábado


def test_parse_chart_keeps_only_new_closed_bars():
    base = int(datetime(2026, 11, 5, 9, 50, tzinfo=COT).timestamp())
    payload = {"chart": {"result": [{"timestamp": [base, base + 60, base + 120, base + 180],
                                     "indicators": {"quote": [{"close": [20000.0, None, 19990.5, 19980.0],
                                                               "volume": [10, 5, None, 7]}]}}]}}
    rows = parse_chart(payload, "NASDAQ", after_ts=base, now_ts=base + 200)
    assert rows == [["2026-11-05 09:52", "NASDAQ", 19990.5, 0]]           # sin la nula, la vieja ni la abierta
    assert parse_chart({"chart": {"result": None}}, "NASDAQ", 0, base) == []


def test_read_series_dedupes(tmp_path):
    p = tmp_path / "b.csv"
    p.write_text("hora_col,moneda,precio\n2026-11-05 09:50,BTC,100\n2026-11-05 09:50,BTC,101\n"
                 "2026-11-05 09:51,ETH,3\n2026-11-05 09:51,BTC,0\n", encoding="utf-8")
    assert [px for _, px in read_series(p, "moneda", "BTC")] == [101.0]
