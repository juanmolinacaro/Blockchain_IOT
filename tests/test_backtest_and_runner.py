from pathlib import Path

from conftest import LEADER, fill, leader_state

from copytrading.backtest import run_backtest
from copytrading.config import Config, LeaderConfig, RiskConfig
from copytrading.execution.paper import PaperExecutor
from copytrading.models import Order
from copytrading.runner import run

H = 3_600_000


def test_paper_executor_pnl_and_flip():
    ex = PaperExecutor(1_000, taker_fee=0, slippage=0)
    ex.execute(Order("ETH", True, 1.0), 100)
    ex.execute(Order("ETH", False, 3.0), 110)          # cierra +10 y abre short 2 @110
    assert ex.realized_pnl == 10
    assert ex.positions["ETH"].size == -2 and ex.positions["ETH"].entry_px == 110
    assert ex.state({"ETH": 100}).equity == 1_000 + 10 + 20


def test_paper_reduce_only_never_increases():
    ex = PaperExecutor(1_000, taker_fee=0, slippage=0)
    ex.execute(Order("ETH", True, 1.0), 100)
    ex.execute(Order("ETH", False, 5.0, reduce_only=True), 100)
    assert "ETH" not in ex.positions


def test_backtest_profitable_leader():
    fills = []
    for i in range(10):
        t = i * 10 * H
        fills.append(fill("ETH", "B", 10, 2000, t, 0.0))
        fills.append(fill("ETH", "A", 10, 2100, t + H, 10.0, pnl=1000, fee=10))
    res = run_backtest(LEADER, fills, leader_equity_now=100_000 + 9_900,
                       risk=RiskConfig(my_equity=10_000, max_position_pct=1.0))
    assert res.leader_return > 0.09
    assert 0 < res.total_return < res.leader_return      # latencia + comisiones restan
    assert 0.5 < res.capture_ratio < 1
    assert res.n_orders == 20


def test_backtest_skips_position_opened_before_window():
    fills = [fill("ETH", "A", 10, 2100, 0, 10.0, pnl=1000)]   # cierre de una posición heredada
    res = run_backtest(LEADER, fills, 100_000, RiskConfig(my_equity=10_000))
    assert res.n_orders == 0 and res.end_equity == 10_000


class FakeSource:
    def __init__(self, states):
        self.states = list(states)

    def size_decimals(self):
        return {"BTC": 5}

    def mid_prices(self):
        return {"BTC": 60_000.0}

    def account_state(self, address):
        return self.states.pop(0)


def test_runner_end_to_end_paper():
    cfg = Config(poll_seconds=0, leaders=[LeaderConfig(LEADER)],
                 risk=RiskConfig(my_equity=10_000, max_position_pct=1.0))
    src = FakeSource([leader_state(), leader_state(BTC=(1.0, 60_000)), leader_state()])
    ex = PaperExecutor(10_000)
    run(cfg, src, ex, max_iterations=3)
    assert [t["side"] for t in ex.trade_log] == ["BUY", "SELL"]
    assert not ex.positions


def test_example_config_loads():
    cfg = Config.load(Path(__file__).resolve().parents[1] / "config.example.toml")
    assert cfg.mode == "paper" and cfg.risk.my_equity == 1000 and cfg.leaders == []
