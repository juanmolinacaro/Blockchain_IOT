"""Modelos de datos compartidos por todo el sistema."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Fill:
    """Una ejecución (trade) de una wallet, tal como queda registrada on-chain."""

    coin: str
    px: float            # precio de ejecución
    sz: float            # tamaño (siempre positivo)
    side: str            # "B" = compra, "A" = venta
    time: int            # timestamp en milisegundos
    start_position: float  # posición firmada ANTES de este fill
    closed_pnl: float = 0.0
    fee: float = 0.0
    direction: str = ""  # "Open Long", "Close Short", ...

    @property
    def signed_sz(self) -> float:
        return self.sz if self.side == "B" else -self.sz

    @property
    def end_position(self) -> float:
        return self.start_position + self.signed_sz

    @property
    def is_closing(self) -> bool:
        """True si el fill reduce (total o parcialmente) una posición existente."""
        return self.start_position != 0 and (self.start_position > 0) != (self.signed_sz > 0)


@dataclass(frozen=True)
class Position:
    coin: str
    size: float          # firmada: >0 long, <0 short
    entry_px: float
    unrealized_pnl: float = 0.0
    leverage: float = 1.0
    liquidation_px: float | None = None

    @property
    def notional(self) -> float:
        return abs(self.size) * self.entry_px


@dataclass
class AccountState:
    """Foto del estado de una cuenta: equity + posiciones abiertas."""

    address: str
    equity: float
    positions: dict[str, Position] = field(default_factory=dict)


@dataclass(frozen=True)
class LeaderboardEntry:
    address: str
    account_value: float
    pnl: dict[str, float]   # ventana -> pnl  ("day", "week", "month", "allTime")
    roi: dict[str, float]
    volume: dict[str, float]


@dataclass(frozen=True)
class Order:
    coin: str
    is_buy: bool
    sz: float
    reduce_only: bool = False
    reason: str = ""


@dataclass
class TraderStats:
    address: str
    n_trades: int = 0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0          # fracción del pico de PnL acumulado + equity
    active_days: int = 0
    avg_hold_minutes: float = 0.0
    top_trade_share: float = 0.0       # % del PnL que viene del mejor trade
    days_since_last_trade: float = 0.0
    trades_per_day: float = 0.0
    account_value: float = 0.0
    score: float = 0.0
    rejected_reasons: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return not self.rejected_reasons
