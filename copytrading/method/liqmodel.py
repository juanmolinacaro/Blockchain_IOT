"""Mapa de liquidaciones estimado a partir de velas (para backtest histórico).

No existe un histórico de posiciones reales, así que se reconstruye como hacen
los mapas tipo TradingDifferent/Coinglass: en cada vela se supone que se abren
longs y shorts proporcionales al volumen, repartidos entre varios
apalancamientos, y se calcula dónde se liquidarían. Cuando el precio cruza un
nivel, esa liquidez queda "absorbida" y desaparece del mapa.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..models import Candle

DEFAULT_LEVERAGE = {10: 0.35, 25: 0.30, 50: 0.20, 100: 0.15}


@dataclass
class LiquidationModel:
    leverage_weights: dict[int, float] = field(default_factory=lambda: dict(DEFAULT_LEVERAGE))
    maintenance: float = 0.004        # margen de mantenimiento aproximado
    bin_pct: float = 0.0025           # ancho de cada nivel (0.25 %)
    decay_per_bar: float = 1.0        # <1: las posiciones se van cerrando solas con el tiempo
    longs: dict[int, float] = field(default_factory=dict)   # bin -> USD que se liquida ahí
    shorts: dict[int, float] = field(default_factory=dict)

    def _bin(self, px: float) -> int:
        return round(math.log(px) / math.log(1 + self.bin_pct))

    def price_of(self, b: int) -> float:
        return (1 + self.bin_pct) ** b

    def update(self, c: Candle) -> tuple[float, float]:
        """Procesa una vela. Devuelve (USD de longs absorbidos, USD de shorts absorbidos)."""
        lo_bin, hi_bin = self._bin(c.l), self._bin(c.h)
        swept_long = sum(v for b, v in self.longs.items() if b >= lo_bin)
        swept_short = sum(v for b, v in self.shorts.items() if b <= hi_bin)
        decay = self.decay_per_bar
        self.longs = {b: v * decay for b, v in self.longs.items() if b < lo_bin and v * decay > 1}
        self.shorts = {b: v * decay for b, v in self.shorts.items() if b > hi_bin and v * decay > 1}

        px = (c.h + c.l + c.c) / 3
        usd = c.v * px
        if usd <= 0:
            return swept_long, swept_short
        for lev, w in self.leverage_weights.items():
            lb = self._bin(px * (1 - 1 / lev + self.maintenance))
            sb = self._bin(px * (1 + 1 / lev - self.maintenance))
            self.longs[lb] = self.longs.get(lb, 0.0) + usd * w
            self.shorts[sb] = self.shorts.get(sb, 0.0) + usd * w
        return swept_long, swept_short

    def zones(self, side: str, top: int = 5) -> list[tuple[float, float]]:
        """Las `top` zonas más cargadas: [(precio, USD)]."""
        book = self.longs if side == "long" else self.shorts
        best = sorted(book.items(), key=lambda kv: kv[1], reverse=True)[:top]
        return [(self.price_of(b), v) for b, v in best]
