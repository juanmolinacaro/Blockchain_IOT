"""Interfaz de una fuente de datos on-chain.

Cualquier cadena/venue (Hyperliquid, un DEX en EVM, Solana...) puede añadirse
implementando este protocolo; el scoring, el backtest y el replicador solo
dependen de él.
"""
from __future__ import annotations

from typing import Protocol

from ..models import AccountState, Fill, LeaderboardEntry


class DataSource(Protocol):
    def leaderboard(self) -> list[LeaderboardEntry]: ...

    def fills(self, address: str, start_ms: int, end_ms: int | None = None) -> list[Fill]: ...

    def account_state(self, address: str) -> AccountState: ...

    def mid_prices(self) -> dict[str, float]: ...

    def size_decimals(self) -> dict[str, int]: ...
