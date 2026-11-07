from copytrading.rendimiento import Rendimiento, from_portfolio, pnl_since

DAY = 86_400_000


def _pf(points, vlm=0.0):
    return {"pnlHistory": [[t, str(v)] for t, v in points], "accountValueHistory": [[points[-1][0], "1000000"]],
            "vlm": str(vlm)}


def test_pnl_since_uses_the_finest_window_covering_the_start():
    pf = [["day", _pf([(10 * DAY, 0), (11 * DAY, 50)])],
          ["week", _pf([(4 * DAY, 0), (6 * DAY, 100), (8 * DAY, 300), (11 * DAY, 250)])],
          ["month", _pf([(0, 0), (11 * DAY, 999)])],
          ["allTime", _pf([(0, 0), (11 * DAY, 999)])]]
    assert pnl_since(pf, 7 * DAY) == 150          # 250 − valor en el día 6 (100), con la serie semanal


def test_from_portfolio_and_verdicts():
    pf = [["day", _pf([(DAY // 2, 0), (DAY, 0)])], ["week", _pf([(0, 0), (DAY, -500_000)], 2e8)],
          ["month", _pf([(0, 0), (DAY, -900_000)], 9e8)], ["allTime", _pf([(0, 0), (DAY, -1e6)])]]
    r = from_portfolio("0xabc", pf, 0)
    assert r.semana == -500_000 and r.mes == -900_000 and r.estudio == -500_000          # la serie semanal ya cubre el inicio
    assert r.veredicto() == "sale (mueve dinero y pierde)"
    assert round(r.por_10k, 1) == -10.0


def test_verdicts_edge_cases():
    base = dict(cuenta="0x1", valor=0, semana=0, mes=0, volumen_semana=0, historico=0)
    assert Rendimiento(estudio=200, volumen_mes=0, **base).veredicto() == "sin actividad"
    assert Rendimiento(estudio=50_000, volumen_mes=0, **base).veredicto() == "se queda"
    assert Rendimiento(estudio=-50_000, volumen_mes=1e6, **base).veredicto() == "sale (pierde)"
    assert Rendimiento(estudio=-50_000, volumen_mes=0, **base).por_10k is None
