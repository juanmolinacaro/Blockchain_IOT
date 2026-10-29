from copytrading.liquidity import (
    GREEN,
    RED,
    YELLOW,
    LiqPoint,
    build_heatmap,
    collect_liquidations,
    insights,
    render_html,
    render_text,
)
from copytrading.models import AccountState, Position
from copytrading.sources.hyperliquid import parse_clearinghouse_state

PRICE = 100_000.0


def pts():
    return [
        LiqPoint("BTC", True, 95_100, 10.0),    # gran bloque de longs a -4.9 %
        LiqPoint("BTC", True, 97_100, 1.0),
        LiqPoint("BTC", True, 98_100, 0.2),
        LiqPoint("BTC", False, 103_100, 3.0),   # shorts a +3.1 %
        LiqPoint("BTC", False, 104_100, 0.5),
        LiqPoint("BTC", False, 130_000, 50.0),  # fuera de rango
        LiqPoint("ETH", True, 95_100, 99.0),    # otra moneda
    ]


def test_bins_sides_and_range():
    hm = build_heatmap(pts(), "BTC", PRICE, range_pct=0.10, band_pct=0.01)
    assert hm.n_positions == 5
    assert len(hm.bands) == 20
    assert abs(hm.usd_below - 11.2 * PRICE) < 1
    assert abs(hm.usd_above - 3.5 * PRICE) < 1
    big = max(hm.bands, key=lambda b: b.total)
    assert big.low <= 95_100 < big.high and big.long_usd == 10 * PRICE and big.short_usd == 0


def test_colors_by_percentile():
    hm = build_heatmap(pts(), "BTC", PRICE, range_pct=0.10, band_pct=0.01)
    levels = {b.level for b in hm.bands if b.total > 0}
    assert levels == {RED, YELLOW, GREEN}
    assert all(b.level == "" for b in hm.bands if b.total == 0)
    assert hm.nearest(above=False).low <= 95_100 < hm.nearest(above=False).high
    assert hm.nearest(above=True) is None                      # arriba solo hay amarillo/verde
    assert hm.nearest(above=True, level=YELLOW).low <= 103_100 < hm.nearest(above=True, level=YELLOW).high


def test_insights_and_renderers():
    hm = build_heatmap(pts(), "BTC", PRICE, range_pct=0.10, band_pct=0.01)
    text = " ".join(insights(hm))
    assert "Zona ROJA más cercana abajo" in text and "Zona más cargada (AMARILLO) arriba" in text
    assert "bajista" in text
    out = render_text(hm)
    assert "precio actual" in out and "🟥" in out
    page = render_html(hm, "2026-10-29")
    assert page.startswith("<!doctype html>") and "#e5484d" in page


def test_empty_map():
    hm = build_heatmap([], "BTC", PRICE)
    assert hm.n_positions == 0 and "No hay posiciones" in insights(hm)[0]


class FakeSource:
    def __init__(self, states):
        self.states = states

    def account_state(self, addr):
        if addr == "bad":
            raise ConnectionError
        return self.states[addr]


def test_collect_skips_errors_and_positions_without_liq_price():
    src = FakeSource({
        "a": AccountState("a", 1, {"BTC": Position("BTC", 2.0, 1, liquidation_px=90_000),
                                   "ETH": Position("ETH", -1.0, 1, liquidation_px=4_000)}),
        "b": AccountState("b", 1, {"BTC": Position("BTC", -1.0, 1, liquidation_px=None)}),
    })
    points = collect_liquidations(src, ["a", "bad", "b"], coin="BTC", pause_s=0)
    assert points == [LiqPoint("BTC", True, 90_000, 2.0)]


def test_parse_liquidation_px():
    raw = {"marginSummary": {"accountValue": "1"}, "assetPositions": [
        {"position": {"coin": "BTC", "szi": "1", "entryPx": "1", "liquidationPx": "85000.5"}},
        {"position": {"coin": "ETH", "szi": "1", "entryPx": "1", "liquidationPx": None}}]}
    st = parse_clearinghouse_state("x", raw)
    assert st.positions["BTC"].liquidation_px == 85000.5
    assert st.positions["ETH"].liquidation_px is None
