from conftest import fill

from copytrading.config import ScoringConfig
from copytrading.models import LeaderboardEntry
from copytrading.scoring import (
    MS_PER_DAY,
    apply_filters,
    compute_stats,
    prefilter_leaderboard,
    round_trips,
    score,
)

H = 3_600_000


def test_round_trips_with_partial_close_and_flip():
    fills = [
        fill("BTC", "B", 1.0, 100, 0, 0.0),
        fill("BTC", "A", 0.5, 110, H, 1.0, pnl=5),
        fill("BTC", "A", 1.5, 120, 2 * H, 0.5, pnl=10, fee=1),   # cierra 0.5 y abre short 1.0
        fill("BTC", "B", 1.0, 115, 3 * H, -1.0, pnl=5),
    ]
    trips = round_trips(fills)
    assert len(trips) == 2
    assert trips[0].pnl == 14 and trips[0].hold_minutes == 120
    assert trips[1].pnl == 5 and trips[1].hold_minutes == 60


def _trader(n_trades, hold_ms, win_pnl=100.0, loss_pnl=-50.0, days=60):
    fills, t = [], 0
    step = days * MS_PER_DAY // n_trades
    for i in range(n_trades):
        pnl = win_pnl if i % 3 else loss_pnl
        fills.append(fill("ETH", "B", 1, 2000, t, 0.0))
        fills.append(fill("ETH", "A", 1, 2000, t + hold_ms, 1.0, pnl=pnl, fee=0.5))
        t += step
    return fills, t


def test_consistent_swing_trader_is_eligible():
    fills, end = _trader(60, 6 * H)
    st = compute_stats("0xgood", fills, 50_000, 0, end)
    apply_filters(st, ScoringConfig())
    assert st.eligible, st.rejected_reasons
    assert 0.6 < st.win_rate < 0.7
    assert st.profit_factor > 2
    assert 0 < score(st, ScoringConfig()) <= 1


def test_hft_bot_is_rejected():
    fills, end = _trader(3000, 30_000, days=30)   # trades de 30 s
    st = apply_filters(compute_stats("0xbot", fills, 50_000, 0, end), ScoringConfig())
    assert not st.eligible
    assert any("rápido" in r for r in st.rejected_reasons)
    assert any("bot" in r for r in st.rejected_reasons)


def test_lucky_single_trade_is_rejected():
    fills, end = _trader(40, 6 * H, win_pnl=1.0, loss_pnl=-1.0)
    fills.append(fill("SOL", "B", 1, 10, end, 0.0))
    fills.append(fill("SOL", "A", 1, 10, end + H, 1.0, pnl=10_000))
    st = apply_filters(compute_stats("0xlucky", fills, 50_000, 0, end + H), ScoringConfig())
    assert any("concentrado" in r for r in st.rejected_reasons)


def test_prefilter_drops_market_makers_and_losers():
    mk = lambda addr, av, month_pnl, vlm: LeaderboardEntry(
        addr, av, {"month": month_pnl, "allTime": 1, "week": 0}, {"month": month_pnl / av}, {"month": vlm})
    rows = [mk("a", 50_000, 5_000, 1e6), mk("mm", 50_000, 9_000, 1e8),
            mk("loser", 50_000, -100, 1e5), mk("small", 500, 400, 1e3)]
    assert [r.address for r in prefilter_leaderboard(rows, ScoringConfig())] == ["a"]
