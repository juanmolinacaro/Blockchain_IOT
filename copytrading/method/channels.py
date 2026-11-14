"""Detección de canales de precio.

Dos formas de trazarlos, ambas sin mirar el futuro (solo usan velas anteriores
a la que se evalúa):

* ``regression_channel``: regresión lineal de los cierres; bordes paralelos donde
  quedan la mayoría de máximos y mínimos de la ventana.
* ``pivot_channels``: como se dibujan a mano. Línea superior por los dos últimos
  máximos relevantes (pivotes) y línea inferior por los dos últimos mínimos. Así
  salen canales paralelos, triángulos y cuñas. Un canal se descarta cuando el
  precio ya ha cerrado claramente fuera de él (la línea está rota).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import Candle


@dataclass(frozen=True)
class Channel:
    up_slope: float
    up_icpt: float
    lo_slope: float
    lo_icpt: float

    def upper(self, x: float) -> float:
        return self.up_icpt + self.up_slope * x

    def lower(self, x: float) -> float:
        return self.lo_icpt + self.lo_slope * x

    def mid(self, x: float) -> float:
        return (self.upper(x) + self.lower(x)) / 2

    @property
    def slope(self) -> float:
        return (self.up_slope + self.lo_slope) / 2

    def slope_pct(self, x: float) -> float:
        """Pendiente media por vela como fracción del precio (alcista > 0, bajista < 0)."""
        return self.slope / self.mid(x)

    def shape(self) -> str:
        if self.up_slope < 0 < self.lo_slope:
            return "triángulo"
        if self.slope > 0:
            return "alcista"
        return "bajista" if self.slope < 0 else "lateral"


def _line(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    slope = (y2 - y1) / (x2 - x1)
    return slope, y1 - slope * x1


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
    icpt = my - slope * mx
    up = max(_quantile([candles[i].h - (icpt + slope * i) for i in xs], q), 0.0)
    down = max(_quantile([(icpt + slope * i) - candles[i].l for i in xs], q), 0.0)
    return Channel(slope, icpt + up, slope, icpt - down)


def find_pivots(candles: list[Candle], k: int) -> tuple[list[int], list[int]]:
    """Índices de máximos y mínimos locales: el extremo de las k velas a cada lado."""
    highs, lows = [], []
    for i in range(k, len(candles) - k):
        window = candles[i - k:i + k + 1]
        if candles[i].h >= max(c.h for c in window):
            highs.append(i)
        if candles[i].l <= min(c.l for c in window):
            lows.append(i)
    return highs, lows


def pivot_channels(candles: list[Candle], k: int = 5, max_age: int = 150,
                   min_gap: int = 5, break_tol: float = 0.005,
                   min_width: float = 0.01) -> list[Channel | None]:
    """Canal vigente para cada vela j, usando solo pivotes ya confirmados (i + k < j)."""
    highs, lows = find_pivots(candles, k)
    out: list[Channel | None] = []
    hi_ptr = lo_ptr = 0
    conf_hi: list[int] = []
    conf_lo: list[int] = []
    for j in range(len(candles)):
        while hi_ptr < len(highs) and highs[hi_ptr] + k < j:
            conf_hi.append(highs[hi_ptr])
            hi_ptr += 1
        while lo_ptr < len(lows) and lows[lo_ptr] + k < j:
            conf_lo.append(lows[lo_ptr])
            lo_ptr += 1
        out.append(_channel_at(candles, j, conf_hi, conf_lo, max_age, min_gap, break_tol, min_width))
    return out


def _last_two(pivots: list[int], min_gap: int) -> tuple[int, int] | None:
    if not pivots:
        return None
    p2 = pivots[-1]
    for p1 in reversed(pivots[:-1]):
        if p2 - p1 >= min_gap:
            return p1, p2
    return None


def _channel_at(candles: list[Candle], j: int, conf_hi: list[int], conf_lo: list[int],
                max_age: int, min_gap: int, break_tol: float, min_width: float) -> Channel | None:
    hp, lp = _last_two(conf_hi, min_gap), _last_two(conf_lo, min_gap)
    if not hp or not lp or j - min(hp[0], lp[0]) > max_age:
        return None
    us, ui = _line(hp[0], candles[hp[0]].h, hp[1], candles[hp[1]].h)
    ls, li = _line(lp[0], candles[lp[0]].l, lp[1], candles[lp[1]].l)
    ch = Channel(us, ui, ls, li)
    if ch.upper(j) <= ch.lower(j) * (1 + min_width):
        return None  # las líneas ya se cruzaron (el triángulo terminó)
    # línea rota: algún cierre desde el último pivote quedó claramente fuera
    for x in range(min(hp[1], lp[1]) + 1, j):
        c = candles[x].c
        if c < ch.lower(x) * (1 - break_tol) or c > ch.upper(x) * (1 + break_tol):
            return None
    return ch
