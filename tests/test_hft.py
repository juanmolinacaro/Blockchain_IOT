from copytrading.hft import HFTProfile, candidates, taker_flow


def _p(maker, fph=50000, median=300, cv=1.0, **kw):
    base = dict(turnover=100, net_ratio=0.1, round_trip_h=0.5, fills_per_order=1.2, twap_share=0.0,
                mean_usd=median)
    base.update(kw)
    return HFTProfile("0x1", 2e9, 1e6, 2e7, fph, maker, median, cv, 50, ["BTC"], **base)


def test_classification_requires_every_signal():
    assert _p(0.16).classify() == "cazador"
    mm = _p(0.85)
    assert mm.classify() == "creador de mercado" and mm.confidence == "alta"
    assert _p(0.6, net_ratio=0.95, cv=0.05, fph=100).classify() == "ejecutor"       # una ballena troceando
    assert _p(0.5, twap_share=0.9).classify() == "ejecutor"                          # TWAP nativo
    # falla una sola señal -> no se etiqueta
    assert _p(0.85, round_trip_h=30).classify() == "sin confirmar"                  # aguanta posición
    assert _p(0.16, turnover=3).classify() == "sin confirmar"                       # poca rotación
    assert _p(0.85, fills_per_order=40).classify() == "sin confirmar"               # "creador" con órdenes enormes
    assert _p(0.16, fills_per_order=40).classify() == "cazador"                     # el cazador sí barre niveles


def test_round_trip_hours():
    from copytrading.hft import _round_trip_hours
    h = 3_600_000
    f = lambda t, side, start: {"coin": "BTC", "time": t, "side": side, "sz": "1", "startPosition": str(start)}
    fills = [f(0, "B", 0), f(h // 2, "A", 1), f(h, "B", 0), f(2 * h, "A", 1)]   # sin posición a 0,5 h y a 2 h
    assert _round_trip_hours(fills) == 1.5


def test_candidates_by_volume_or_turnover():
    row = lambda a, vol, acct: {"ethAddress": a, "accountValue": str(acct),
                                "windowPerformances": [["week", {"vlm": str(vol), "pnl": "0"}]]}
    rows = [row("0xbig", 2e9, 1e8), row("0xturn", 6e8, 1e7), row("0xslow", 1e8, 1e8)]
    assert [c["address"] for c in candidates(rows)] == ["0xbig", "0xturn"]


def test_taker_flow_counts_only_the_aggressor():
    trades = [{"users": ["0xbot", "0xmm"], "side": "B", "px": "80000", "sz": "1"},   # el robot compra agresivo
              {"users": ["0xmm", "0xbot"], "side": "B", "px": "80000", "sz": "2"}]   # el agresor es 0xmm
    flow = taker_flow(trades, {"0xbot": "cazador", "0xmm": "creador de mercado"})
    assert flow["cazador"] == {"compra": 80000.0, "venta": 0.0}
    assert flow["creador de mercado"]["compra"] == 160000.0
