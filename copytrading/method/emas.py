"""EMAs en la misma temporalidad o en una mayor (p. ej. la EMA diaria sobre velas de 4H).

Formato de especificación: "1d:200,4h:200" (temporalidad:longitud). En una
temporalidad mayor se usa el valor del último periodo CERRADO, para no mirar
el futuro (el día en curso aún no ha terminado).
"""
from __future__ import annotations

from ..models import Candle

PERIOD_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1w": 604_800_000}


def parse_spec(spec: str) -> list[tuple[str, int]]:
    out = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        tf, length = part.split(":")
        if tf not in PERIOD_MS:
            raise ValueError(f"Temporalidad no soportada en la EMA: {tf}")
        out.append((tf, int(length)))
    return out


def ema_series(candles: list[Candle], tf: str, length: int) -> list[float | None]:
    """Valor de la EMA disponible al cierre de cada vela (None durante el calentamiento)."""
    period = PERIOD_MS[tf]
    alpha = 2 / (length + 1)
    out: list[float | None] = []
    ema, n_closed = None, 0
    cur_period, cur_close = None, None
    closed_value: float | None = None
    bar_ms = candles[1].t - candles[0].t if len(candles) > 1 else period
    same_tf = period <= bar_ms
    for c in candles:
        p = c.t // period
        if cur_period is not None and p != cur_period:
            # se cerró el periodo anterior: actualizar la EMA con su cierre
            ema = cur_close if ema is None else alpha * cur_close + (1 - alpha) * ema
            n_closed += 1
            closed_value = ema if n_closed >= length else None
        cur_period, cur_close = p, c.c
        if same_tf:
            # misma temporalidad: la vela actual ya está cerrada al evaluarla
            live = cur_close if ema is None else alpha * cur_close + (1 - alpha) * ema
            out.append(live if n_closed + 1 >= length else None)
        else:
            out.append(closed_value)
    return out


def compute_emas(candles: list[Candle], spec: str) -> list[list[float]]:
    """Para cada vela, la lista de valores de EMA disponibles (se omiten las que aún calientan)."""
    series = [ema_series(candles, tf, n) for tf, n in parse_spec(spec)]
    return [[s[i] for s in series if s[i] is not None] for i in range(len(candles))]
