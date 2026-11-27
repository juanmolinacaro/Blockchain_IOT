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


def _r(cuenta, estudio, pico, vol=5e8):
    return Rendimiento(cuenta, 0, 0, 0, estudio, 0, vol, 0, pico)


def test_tolerance_band_for_the_alert():
    from copytrading.rendimiento import select_winners
    rows = [_r("0xbig", 1_260_000, 1_300_000),          # gana de verdad: entra
            _r("0xsmall", 60_000, 80_000),              # gana poco: no entra todavía
            _r("0xdip", 700_000, 1_300_000),            # ya estaba, conserva más de la mitad del pico: se queda
            _r("0xfell", 500_000, 1_300_000),           # ya estaba, perdió más de la mitad del pico: sale
            _r("0xneg", -10_000, 200_000),              # ya estaba, quedó en pérdidas: sale
            _r("0xidle", 900_000, 900_000, vol=0)]      # gana pero no opera: su empuje no cuenta
    got = select_winners(rows, previous={"0xdip", "0xfell", "0xneg", "0xsmall"})
    assert got == {"0xbig", "0xdip", "0xsmall"}          # 0xsmall ya estaba y conserva más de la mitad
    assert select_winners(rows) == {"0xbig", "0xdip"}    # sin historia: solo entran las de más de $100k


def test_peak_and_last_winners(tmp_path):
    from copytrading.rendimiento import last_winners, save
    noon = 17 * 3_600_000                                   # mediodía en Colombia (UTC−5)
    pf = [["day", _pf([(3 * DAY, 0), (3 * DAY + 1, 0)])],
          ["week", _pf([(0, 0), (noon, 900_000), (DAY + 5 * 3_600_000 - 1, 300_000),   # pico de media tarde: ruido
                        (DAY + noon, 100_000), (2 * DAY + noon, 150_000)], 1e8)],
          ["month", _pf([(0, 0), (2 * DAY, 150_000)], 1e8)], ["allTime", _pf([(0, 0), (2 * DAY, 150_000)])]]
    r = from_portfolio("0xa", pf, 0)
    assert r.estudio == 150_000 and r.pico == 300_000       # cierre del primer día, no el +900k de dentro del día
    p = tmp_path / "h.jsonl"
    save([r, _r("0xb", -5, 0)], p, winners={"0xa"})
    save([r, _r("0xb", -5, 0)], p, winners=set())
    assert last_winners(p) == set()


def test_history_keeps_a_good_account_in_a_bad_streak():
    base = dict(cuenta="0x1", valor=0, semana=0, mes=0, volumen_semana=0, volumen_mes=3e9, estudio=-500_000, pico=0)
    cambista = Rendimiento(historico=228e6, volumen_historico=324e9, **base)          # +7 por $10k
    assert cambista.gana_historico and cambista.veredicto() == "se queda (mala racha: gana en su historial)"
    arbitraje = Rendimiento(historico=0.32e6, volumen_historico=81e9, **base)         # 0xf5d8: en cero
    assert not arbitraje.gana_historico and arbitraje.veredicto() == "sale (mueve dinero y pierde)"
    perdedora = Rendimiento(historico=-264e6, volumen_historico=36e9, **base)
    assert perdedora.veredicto().startswith("sale")
    assert Rendimiento(historico=0, volumen_historico=0, **base).por_10k_historico is None


def test_history_loser_on_a_good_streak_is_only_observed():
    from copytrading.rendimiento import select_winners
    r = Rendimiento("0x7b7f", 0, 0, 0, 1_200_000, 0, 6e9, -24.9e6, 1_300_000, 194e9)
    assert r.veredicto().startswith("en observación")
    assert select_winners([r]) == set() and select_winners([r], previous={"0x7b7f"}) == set()
