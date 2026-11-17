"""Liquidez de corto plazo: posiciones muy apalancadas (25x–100x) abiertas en los últimos días.

El mapa principal usa velas de 4H con memoria de 2 semanas y capta los bloques grandes y viejos.
Esta capa usa velas de 1H, memoria corta (vida media 24 h) y solo apalancamiento alto, como el
mapa de 1H/5M de La Ruta del Precio. Validación (3 nov 2026): marcó cortos en 78.114 / 78.309
frente a sus 78.137 / 78.353, y largos en 75.431–76.188 frente a su bloque 75.000–76.270.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import Candle
from .liqmodel import LiquidationModel

SHORT_TERM_LEVERAGE = {25: 0.30, 50: 0.35, 100: 0.35}


@dataclass
class STZone:
    side: str          # "long" (debajo del precio) | "short" (encima)
    center: float
    usd: float


def short_term_zones(candles_1h: list[Candle], half_life_h: float = 24, rng: float = 0.04,
                     merge_pct: float = 0.004, top: int = 2) -> tuple[list[STZone], list[STZone]]:
    """Zonas más cargadas a ±`rng` del precio: (largos debajo, cortos encima), de mayor a menor."""
    model = LiquidationModel(leverage_weights=dict(SHORT_TERM_LEVERAGE), decay_per_bar=0.5 ** (1 / half_life_h))
    for c in candles_1h:
        model.update(c)
    px = candles_1h[-1].c
    out = []
    for side, book in (("long", model.longs), ("short", model.shorts)):
        lvls = {b: v for b, v in book.items() if abs(model.price_of(b) / px - 1) <= rng}
        zones, used = [], set()
        width = max(1, round(merge_pct / model.bin_pct))     # vecinos que cuentan como la misma zona
        for b in sorted(lvls, key=lambda k: -lvls[k]):        # picos de mayor a menor
            if b in used:
                continue
            group = [k for k in range(b - width, b + width + 1) if k in lvls and k not in used]
            used.update(range(b - width, b + width + 1))
            usd = sum(lvls[k] for k in group)
            zones.append(STZone(side, model.price_of(b), usd))
            if len(zones) == top:
                break
        out.append(zones)
    return out[0], out[1]


def describe(longs: list[STZone], shorts: list[STZone], fmt=lambda p: f"{p:,.0f}") -> list[str]:
    if not longs and not shorts:
        return ["Corto plazo: sin liquidez apalancada relevante a ±4 %"]
    lines = []
    if shorts:
        lines.append("Corto plazo arriba (cortos 25-100x): " + " · ".join(fmt(z.center) for z in shorts))
    if longs:
        lines.append("Corto plazo abajo (largos 25-100x): " + " · ".join(fmt(z.center) for z in longs))
    up, down = sum(z.usd for z in shorts), sum(z.usd for z in longs)
    if up and down:
        big, small, where = (up, down, "arriba") if up >= down else (down, up, "abajo")
        if big >= 2 * small:
            lines.append(f"Corto plazo: imán {where} ({big / small:.1f}x más liquidez)")
    return lines
