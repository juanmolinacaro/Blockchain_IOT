"""Detección de canales de precio.

Canal de regresión lineal sobre las últimas `lookback` velas: la línea central es
la regresión de los cierres y los bordes se colocan donde quedan la mayoría de
máximos y mínimos de la ventana (cuantil `q` de las desviaciones). Solo usa
velas anteriores a la que se evalúa, así que no mira el futuro.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import Candle


@dataclass(frozen=True)
class Channel:
    slope: float
    intercept: float
    up: float     # distancia del centro al borde superior
    down: float   # distancia del centro al borde inferior

    def mid(self, x: float) -> float:
        return self.intercept + self.slope * x

    def upper(self, x: float) -> float:
        return self.mid(x) + self.up

    def lower(self, x: float) -> float:
        return self.mid(x) - self.down

    def slope_pct(self, x: float) -> float:
        """Pendiente por vela como fracción del precio (para clasificar alcista/bajista)."""
        return self.slope / self.mid(x)


def _quantile(vals: list[float], q: float) -> float:
    s = sorted(vals)
    idx = q * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


def regression_channel(candles: list[Candle], end: int, lookback: int, q: float = 0.9) -> Channel | None:
    """Canal ajustado a las velas [end - lookback, end) (sin incluir `end`)."""
    start = end - lookback
    if start < 0 or lookback < 3:
        return None
    xs = list(range(start, end))
    ys = [candles[i].c for i in xs]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    intercept = my - slope * mx
    ch = Channel(slope, intercept, 0.0, 0.0)
    up = _quantile([candles[i].h - ch.mid(i) for i in xs], q)
    down = _quantile([ch.mid(i) - candles[i].l for i in xs], q)
    return Channel(slope, intercept, max(up, 0.0), max(down, 0.0))
