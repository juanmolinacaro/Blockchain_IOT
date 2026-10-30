from copytrading.models import Fill
from copytrading.smartwallets import Event, evaluate, rank

D = 86_400_000
BOTTOM = Event("suelo", "BTC", 10 * D, 13 * D, 58_000)
TOP = Event("techo", "BTC", 80 * D, 95 * D, 87_000)


def f(day, side, sz, px, start_pos=0.0, pnl=0.0):
    return Fill("BTC", px, sz, side, day * D, start_pos, closed_pnl=pnl)


def test_master_wallet_bought_bottom_held_and_sold_top():
    fills = [f(11, "B", 10, 58_500), f(85, "A", 10, 86_000, start_pos=10, pnl=275_000)]
    s = evaluate("0xmaster", fills, [BOTTOM, TOP])
    assert s.label == "maestra" and s.bottoms == 1 and s.tops == 1
    assert s.held and s.realized == 275_000


def test_late_buyer_is_not_a_bottom_hit():
    s = evaluate("0xlate", [f(12, "B", 10, 63_000)], [BOTTOM])    # 8,6 % por encima del suelo
    assert s.bottoms == 0


def test_small_or_flat_activity_does_not_count():
    s = evaluate("0xsmall", [f(11, "B", 1, 58_000)], [BOTTOM])     # 58k USD < mínimo
    assert s.bottoms == 0
    s = evaluate("0xflat", [f(11, "B", 10, 58_000), f(12, "A", 10, 58_200)], [BOTTOM])
    assert s.bottoms == 0


def test_rank_orders_by_events_then_pnl():
    data = {
        "0xa": [f(11, "B", 10, 58_500), f(85, "A", 10, 86_000, 10, 100)],
        "0xb": [f(85, "A", 10, 86_500, 10, 500_000)],
        "0xc": [f(50, "B", 10, 70_000)],
    }
    r = rank(data, [BOTTOM, TOP])
    assert [s.address for s in r] == ["0xa", "0xb"]
