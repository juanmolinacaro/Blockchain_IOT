from types import SimpleNamespace

from copytrading.avisos import classify, measure, report

T0 = 1_794_174_000_000


def _ev(sec, tipo, moneda="BTC", **kw):
    return {"t": T0 + sec * 1000, "tipo": tipo, "moneda": moneda, "precio": 100.0, **kw}


def test_classify_pairs_two_sided_withdrawals():
    evs = [_ev(0, "retiro-BTC-compras", lado="compras"), _ev(1, "retiro-BTC-ventas", lado="ventas"),
           _ev(600, "retiro-BTC-compras", lado="compras"),
           _ev(700, "empuje-BTC-VENDEN", grupo="ganadoras"), _ev(800, "empuje-BTC-COMPRAN"),
           _ev(900, "liq-binance-BTC-largos")]
    got = [(c, d) for _, c, d in classify(evs)]
    assert got == [("retiro-ambos", 0), ("retiro-un-lado", -1), ("empuje-ganadoras", -1),
                   ("empuje-cazadores", 1), ("liq-binance", -1)]


def test_measure_hits_by_direction():
    candles = {"BTC": [SimpleNamespace(t=T0 - 60_000 + i * 60_000, c=100.0 - i * 0.1) for i in range(90)]}
    m = measure([_ev(0, "empuje-BTC-VENDEN", grupo="ganadoras"), _ev(0, "empuje-BTC-COMPRAN")], candles)
    assert m[0].acierto(15) is True and m[0].acierto(60) is True     # vendieron y el precio bajó
    assert m[1].acierto(15) is False
    lines = report(m, {"BTC": 0.002})
    assert any("cuentas que ganan: 1 avisos · acierto 15 min 1/1" in line for line in lines)
