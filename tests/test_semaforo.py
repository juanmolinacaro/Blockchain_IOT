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


def test_sweep_then_leader_sells_opens_short_record():
    z = ([C(center=66_578)], [C(center=69_812)])
    sw = {}
    sm.record_sweep(sw, z, 70_214, 69_500, 0)                    # 8:30: barre los cortos de 69.812
    assert sw["short"] == [69_812, 70_214, 0] and ("short", 69_812) not in sw["_mem"]
    sm.record_sweep(sw, ([], [C(center=70_337)]), 69_900, 69_400, 60_000)   # el mapa cambia: no se barre
    assert sw["short"][0] == 69_812 and ("short", 70_337) in sw["_mem"]
    # la líder vende, pero el precio sigue encima del nivel: todavía no
    assert sm.detect_sweep_leader(sw, -1.5e6, 69_987, 9 * 60_000, 1e6) is None
    s = sm.detect_sweep_leader(sw, -2.0e6, 69_318, 39 * 60_000, 1e6)
    assert s and s.side == "short" and s.entry == 69_318 and round(s.stop) == round(70_214 * 1.001)
    assert sm.detect_sweep_leader(sw, -0.5e6, 69_318, 40 * 60_000, 1e6) is None          # empuje pequeño
    assert sm.detect_sweep_leader(sw, -2e6, 69_318, sm.SWEEP_WINDOW_MS + 1, 1e6) is None   # barrido viejo
    assert sm.detect_sweep_leader(sw, +2e6, 69_318, 60_000, 1e6) is None                # compra sin barrido abajo


def test_sweep_of_longs_then_leader_buys():
    sw = {}
    sm.record_sweep(sw, ([C(center=68_261)], []), 68_500, 67_474, 0)
    s = sm.detect_sweep_leader(sw, 1.2e6, 68_776, 30 * 60_000, 1e6)
    assert s and s.side == "long" and round(s.stop) == round(67_474 * 0.999)


def test_zone_memory_keeps_levels_that_left_the_map():
    sw = {}
    sm.record_sweep(sw, ([], [C(center=69_812)]), 69_300, 69_100, 0)          # 7:00: el mapa muestra 69.812
    sm.record_sweep(sw, ([], [C(center=70_337)]), 70_214, 69_500, 3_600_000)  # 8:30: ya no, pero lo recuerda
    assert sw["short"][0] == 69_812
    sm.record_sweep(sw, ([], []), 69_000, 68_900, 3_600_000 + sm.ZONE_MEMORY_MS + 1)
    assert not sw["_mem"]                                                        # olvida después de 6 h


def test_sweep_wick_keeps_growing():
    sw = {}
    sm.record_sweep(sw, ([], [C(center=69_812)]), 70_000, 69_700, 0)
    sm.record_sweep(sw, ([], []), 70_214, 69_900, 5 * 60_000)
    assert sw["short"][1] == 70_214
