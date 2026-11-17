from types import SimpleNamespace as C

from copytrading.method.rupturas import Ruptura, acumulacion, compresion, outcome


def _flat(n, lo=99.8, hi=100.2, start=0):
    return [C(t=start + i, o=100, h=hi if i % 3 == 0 else 100.1, l=lo if i % 3 == 1 else 99.9, c=100) for i in range(n)]


def test_compression_and_range_breaks():
    wide = [C(t=i, o=100, h=104, l=96, c=100) for i in range(200)]
    c = wide + _flat(40, start=200) + [C(t=300, o=100, h=100, l=98.9, c=99.0)]
    assert any(r.lado == "short" for r in compresion(c))
    assert any(r.tipo == "acumulación" and r.lado == "short" for r in acumulacion(c))


def test_outcome_counts_fee_and_juan_rule():
    c = [C(t=0, o=100, h=100, l=100, c=100), C(t=1, o=100, h=100.2, l=98.9, c=99), C(t=2, o=99, h=99, l=97.9, c=98)]
    r = Ruptura("compresión", 0, "short", 100.0, 101.0)
    res = outcome(c, r, horizon=5)
    assert round(res[1.0], 3) == round(1.0 - 0.0009 * 100, 3)          # tocó 1R, menos comisión
    assert round(res["juan"], 3) == round(1.5 - 0.09, 3)               # mitad en 1R y resto a 2R
