from types import SimpleNamespace as C

from copytrading.method.monitor import activate_plan, manual_plan

H = 3_600_000


def _plan():
    return manual_plan("BTC", "short", 73900, "below", 74900, 72230, 0, hours=48, sweep=74124,
                       now_ms=10 * H, start_ms=10 * H)


def test_far_confirmation_turns_into_limit_order():
    e = _plan()
    cs = [C(t=10 * H, o=74000, h=74150, l=73650, c=73700),     # barre 74.124 y cierra a 0,61 % del máximo
          C(t=11 * H, o=73700, h=73800, l=73500, c=73600),     # no vuelve a 73.900: sigue esperando
          C(t=12 * H, o=73600, h=73950, l=73550, c=73850)]     # vuelve a 73.900: se llena la orden límite
    activate_plan(e, cs)
    assert e.status == "abierta" and e.entry == 73900 and e.time == 12 * H and "orden límite" in e.note


def test_close_near_sweep_enters_at_close():
    e = _plan()
    activate_plan(e, [C(t=10 * H, o=74000, h=74150, l=73700, c=73780)])   # 0,16 % bajo el gatillo: espera
    assert e.status == "pendiente"
    e3 = _plan()
    activate_plan(e3, [C(t=10 * H, o=74000, h=74150, l=73800, c=73850)])  # 0,07 % bajo el gatillo: entra al cierre
    assert e3.status == "abierta" and e3.entry == 73850


def test_limit_cancelled_if_it_runs_to_tp1():
    e = _plan()
    activate_plan(e, [C(t=10 * H, o=74000, h=74150, l=73650, c=73700),
                      C(t=11 * H, o=73700, h=73750, l=72200, c=72300)])
    assert e.status == "anulada"
