"""Configuración de la estrategia (se carga desde un archivo TOML)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class ScoringConfig:
    """Filtros duros y pesos para seleccionar traders a seguir."""

    min_trades: int = 30
    min_active_days: int = 14
    min_account_value: float = 10_000.0
    min_win_rate: float = 0.40
    min_profit_factor: float = 1.3
    max_drawdown: float = 0.35
    max_top_trade_share: float = 0.40   # evita "un golpe de suerte"
    min_avg_hold_minutes: float = 15.0  # traders más rápidos que esto no se pueden copiar (latencia)
    max_trades_per_day: float = 50.0    # descarta market makers / bots HFT
    max_days_since_last_trade: float = 7.0
    lookback_days: int = 90


@dataclass
class RiskConfig:
    my_equity: float = 1_000.0            # capital asignado a la estrategia (USD)
    size_multiplier: float = 1.0          # 1.0 = misma exposición relativa que el líder
    max_leverage: float = 3.0             # exposición bruta total / equity
    max_position_pct: float = 0.25        # notional máximo por moneda / equity
    min_order_usd: float = 11.0           # Hyperliquid exige ~10 USD mínimo
    rebalance_threshold_pct: float = 0.10 # no ajustar si la diferencia es < 10 % del objetivo
    max_entry_deviation_pct: float = 0.01 # no entrar si el precio ya se alejó >1 % de la entrada del líder
    copy_existing_positions: bool = False # no entrar en posiciones que el líder abrió antes de empezar
    stop_loss_pct: float = 0.08           # stop propio por posición (independiente del líder)
    daily_loss_limit_pct: float = 0.05    # kill-switch diario
    allowed_coins: list[str] = field(default_factory=list)   # vacío = todas
    blocked_coins: list[str] = field(default_factory=list)


@dataclass
class LeaderConfig:
    address: str
    weight: float = 1.0   # fracción del capital asignada a este líder (se normaliza)


@dataclass
class Config:
    network: str = "mainnet"          # "mainnet" | "testnet"
    mode: str = "paper"               # "paper" | "live"
    poll_seconds: float = 5.0
    leaders: list[LeaderConfig] = field(default_factory=list)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        return cls(
            network=raw.get("network", "mainnet"),
            mode=raw.get("mode", "paper"),
            poll_seconds=float(raw.get("poll_seconds", 5.0)),
            leaders=[LeaderConfig(**l) for l in raw.get("leaders", [])],
            scoring=_build(ScoringConfig, raw.get("scoring", {})),
            risk=_build(RiskConfig, raw.get("risk", {})),
        )


def _build(cls, values: dict):
    known = {f.name for f in fields(cls)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"Claves desconocidas en [{cls.__name__}]: {sorted(unknown)}")
    return cls(**values)
