from copytrading.candidatas import report, select
from copytrading.models import LeaderboardEntry
from copytrading.rendimiento import Rendimiento


def _e(a, hist, month, vh, vm, value=5e6):
    return LeaderboardEntry(a, value, {"allTime": hist, "month": month, "week": 0}, {}, {"allTime": vh, "month": vm})


def test_select_filters_and_orders_by_monthly_efficiency():
    board = [_e("0xgood", 50e6, 5e6, 60e9, 4e9),          # ef. mes 12,5
             _e("0xbetter", 20e6, 3e6, 20e9, 2e9),        # ef. mes 15
             _e("0xlazy", 50e6, 5e6, 60e9, 0.5e9),        # no opera lo suficiente
             _e("0xcold", 50e6, -1e6, 60e9, 4e9),         # el mes en pérdida
             _e("0xchurn", 6e6, 1e6, 300e9, 4e9),         # historial poco eficiente (0,2)
             _e("0xin", 90e6, 9e6, 60e9, 4e9)]            # ya está en la cohorte
    got = select(board, {"0xin"})
    assert [r["cuenta"] for r in got] == ["0xbetter", "0xgood"]
    assert "ef. mes" in report(got)[0]


def test_group_with_subaccounts_keeps_the_account():
    base = dict(cuenta="0xf5d8", valor=0, semana=0, mes=-300_000, estudio=-400_000, volumen_semana=0,
                volumen_mes=17e9, historico=200_000, pico=0, volumen_historico=81e9)
    r = Rendimiento(**base, grupo_mes=44.5e6, grupo_historico=42.2e6)
    assert r.veredicto() == "se queda (gana con sus subcuentas)"
    neg = Rendimiento(**{**base, "historico": -264e6}, grupo_mes=3.4e6, grupo_historico=15.8e6)
    assert not neg.pierde_historico and neg.veredicto() == "se queda (gana con sus subcuentas)"
    assert Rendimiento(**base).veredicto() == "sale (mueve dinero y pierde)"
