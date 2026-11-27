import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from copytrading.models import AccountState, Fill, Position  # noqa: E402

LEADER = "0xleader"


def fill(coin, side, sz, px, t, start, pnl=0.0, fee=0.0):
    return Fill(coin=coin, px=px, sz=sz, side=side, time=t, start_position=start,
                closed_pnl=pnl, fee=fee)


def leader_state(equity=100_000.0, **positions):
    """leader_state(BTC=(1.0, 60000)) -> cuenta con 1 BTC long a 60k."""
    return AccountState(LEADER, equity,
                        {c: Position(c, sz, px) for c, (sz, px) in positions.items()})
