from copytrading.hft import HFTProfile, candidates, taker_flow


def _p(fph, maker, cv):
    return HFTProfile("0x1", 2e9, 1e6, 5e7, fph, maker, 300, cv, 10, ["BTC"])


def test_classification():
    assert _p(12000, 0.16, 1.0).classify() == "cazador"
    assert _p(6000, 0.80, 1.0).classify() == "creador de mercado"
    assert _p(100, 0.60, 0.05).classify() == "ejecutor"
    assert _p(3000, 0.5, 1.0).classify() == "mixto"


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
