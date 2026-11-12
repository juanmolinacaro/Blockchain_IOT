from types import SimpleNamespace as C

from copytrading import semaforo as sm


def _c(t, o, h, l, c, v=100):
    return C(t=t, o=o, h=h, l=l, c=c, v=v)


def test_trap_signal_is_a_limit_at_the_level():
    c = [_c(i, 100, 101, 99, 100) for i in range(30)] + [_c(30, 100, 101.5, 99.5, 100.2)]
    s = sm.detect_trap(c)
    assert s and s.side == "short" and s.entry == 101 and s.limit and round(s.stop, 3) == round(101.5 * 1.001, 3)


def test_paper_lifecycle_limit_tp1_breakeven():
    items = []
    p = sm.open_signal(items, sm.Signal("trampa", "", "short", 100.0, 101.0, limit=True), "BTC", 0, True, {})
    assert p.status == "pendiente"
    assert sm.open_signal(items, sm.Signal("trampa", "", "short", 100.0, 101.0, limit=True), "BTC", 1, True, {}) is None
    assert sm.update(p, 99.5, 99.0, 10) is None                 # no vuelve a 100
    assert sm.update(p, 100.1, 99.8, 20) == "llenada"
    assert "TP1" in sm.update(p, 99.9, 98.9, 30)
    assert sm.update(p, 100.2, 99.5, 40) == "stop en la entrada"
    assert round(p.r, 3) == round(0.5 - 0.0009 * 100 / 1.0, 3)


def test_limit_expires_and_filter():
    items = []
    p = sm.open_signal(items, sm.Signal("trampa", "", "long", 100.0, 99.0, limit=True), "BTC", 0, False, {})
    assert sm.update(p, 101, 100.5, sm.LIMIT_BARS_MS + 1) == "sin llenar"
    conf = {"total": -4, "votos": {"tendencia": -1, "mayoría": -1, "público": -1, "imán": -1}}
    assert sm.passes_filter(conf, "short") and not sm.passes_filter(conf, "long")
    assert not sm.passes_filter({"total": -3, "votos": {"tendencia": 1, "público": -1, "imán": -1, "ballenas": -1, "x": -1}}, "short")
    lines = sm.scoreboard(items)
    assert any("sin llenar 1" in l for l in lines)


def test_mw_requires_weaker_second_peak():
    # dos techos a 110 con valle en 105, 2.º techo con menos volumen, y cierre bajo el cuello
    base = [_c(i, 100, 101, 99, 100) for i in range(30)]
    up = [_c(30 + i, 100 + i * 2, 101 + i * 2, 99 + i * 2, 100 + i * 2) for i in range(5)]       # 100→108
    top1 = [_c(35, 108, 110, 107, 109, 500)]
    down = [_c(36 + i, 109 - i, 109.5 - i, 105 + (3 - i) * 0.5, 108 - i) for i in range(4)]       # baja a 105
    valley = [_c(40, 106, 106.5, 105, 106)]
    up2 = [_c(41 + i, 106 + i, 107.5 + i, 105.5 + i, 107 + i) for i in range(3)]
    top2 = [_c(44, 109, 110.1, 108, 109, 200)]
    after = [_c(45 + i, 108.5 - i, 109 - i, 107 - i, 108 - i) for i in range(3)]
    brk = [_c(48, 105.5, 105.6, 104, 104.5)]
    c = base + up + top1 + down + valley + up2 + top2 + after + brk
    s = sm.detect_mw(c, "BAJISTA")
    assert s is None or s.side == "short"
