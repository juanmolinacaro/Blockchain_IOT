"""Trampas del precio: rupturas falsas frente a rupturas reales.

Ruptura: una vela cierra por encima del máximo (o por debajo del mínimo) de las `lookback` velas
anteriores. Trampa: en las `hold` velas siguientes el precio vuelve a cerrar dentro del rango.
Para cada ruptura se guardan rasgos medibles en el momento de la ruptura (sin mirar el futuro),
para ver cuáles separan las trampas de las rupturas reales.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone

from ..models import Candle
from .emas import ema_series


@dataclass
class Breakout:
    i: int
    up: bool
    level: float            # máximo/mínimo roto
    opposite: float         # el otro extremo del rango
    vol_ratio: float        # volumen de la vela de ruptura / volumen medio del rango
    excess: float           # cuánto cierra más allá del nivel (fracción)
    wick: float             # mecha en contra / rango de la vela (0 = cierre en el extremo)
    width: float            # ancho del rango previo (fracción): compresión
    weekend: bool
    session: str            # Asia / Europa / EEUU / Tarde
    with_trend: bool | None # a favor de la EMA 50 diaria
    trap: bool = False
    reached_opposite: bool = False   # tras la trampa, llegó al otro extremo del rango
    follow: float = 0.0     # recorrido a favor en las 24 velas siguientes (si no fue trampa)


def _session(t: int) -> tuple[bool, str]:
    d = datetime.fromtimestamp(t / 1000, timezone.utc)
    weekend = d.weekday() == 5 or d.weekday() == 6 or (d.weekday() == 4 and d.hour >= 20)
    h = d.hour
    return weekend, ("Asia" if h < 8 else "Europa" if h < 13 else "EEUU" if h < 21 else "Tarde")


def find_breakouts(candles: list[Candle], lookback: int = 24, hold: int = 6,
                   after: int = 24, cooldown: int = 6) -> list[Breakout]:
    ema50 = ema_series(candles, "1d", 50)
    out: list[Breakout] = []
    i = lookback
    while i < len(candles) - max(hold, after) - 1:
        win = candles[i - lookback:i]
        hi, lo = max(c.h for c in win), min(c.l for c in win)
        c = candles[i]
        up, down = c.c > hi, c.c < lo
        if not (up or down):
            i += 1
            continue
        level, opposite = (hi, lo) if up else (lo, hi)
        avg_vol = statistics.fmean(x.v for x in win) or 1.0
        rng = (c.h - c.l) or 1e-9
        wick = (c.h - c.c) / rng if up else (c.c - c.l) / rng
        weekend, session = _session(c.t)
        e = ema50[i]
        b = Breakout(i, up, level, opposite, c.v / avg_vol, abs(c.c / level - 1), wick,
                     (hi - lo) / lo, weekend, session, (c.c > e) == up if e else None)
        nxt = candles[i + 1:i + 1 + hold]
        b.trap = any((x.c < level) if up else (x.c > level) for x in nxt)
        later = candles[i + 1:i + 1 + after]
        if b.trap:
            b.reached_opposite = any((x.l <= opposite) if up else (x.h >= opposite) for x in later)
        else:
            b.follow = (max(x.h for x in later) / c.c - 1) if up else (1 - min(x.l for x in later) / c.c)
        out.append(b)
        i += cooldown
    return out


def _rate(group: list[Breakout]) -> str:
    return f"{sum(b.trap for b in group) / len(group):.0%} trampas ({len(group)} casos)" if group else "-"


def report(name: str, bks: list[Breakout]) -> list[str]:
    if not bks:
        return [f"## {name}", "Sin rupturas."]
    L = [f"## {name}", f"Rupturas: {len(bks)} · **trampas: {sum(b.trap for b in bks) / len(bks):.0%}**", ""]
    traps = [b for b in bks if b.trap]
    real = [b for b in bks if not b.trap]
    if traps:
        L.append(f"Tras una trampa, el precio llega al otro extremo del rango en 24 velas: "
                 f"**{sum(b.reached_opposite for b in traps) / len(traps):.0%}**")
    if real:
        L.append(f"Ruptura real: recorrido mediano a favor en 24 velas: {statistics.median(b.follow for b in real):.1%}")
    L.append("")
    vq = sorted(b.vol_ratio for b in bks)
    v_lo, v_hi = vq[len(vq) // 3], vq[2 * len(vq) // 3]
    wq = sorted(b.width for b in bks)
    w_mid = wq[len(wq) // 2]
    rows = [
        ("Volumen bajo (tercio inferior)", [b for b in bks if b.vol_ratio <= v_lo]),
        ("Volumen alto (tercio superior)", [b for b in bks if b.vol_ratio >= v_hi]),
        ("Cierre con mecha larga en contra (>40 % de la vela)", [b for b in bks if b.wick > 0.4]),
        ("Cierre cerca del extremo (mecha <15 %)", [b for b in bks if b.wick < 0.15]),
        ("Cierra apenas fuera (<0,2 %)", [b for b in bks if b.excess < 0.002]),
        ("Cierra claramente fuera (>0,6 %)", [b for b in bks if b.excess > 0.006]),
        ("Rango previo estrecho (compresión)", [b for b in bks if b.width <= w_mid]),
        ("Rango previo ancho", [b for b in bks if b.width > w_mid]),
        ("Fin de semana", [b for b in bks if b.weekend]),
        ("Entre semana", [b for b in bks if not b.weekend]),
        ("A favor de la EMA 50 diaria", [b for b in bks if b.with_trend is True]),
        ("En contra de la EMA 50 diaria", [b for b in bks if b.with_trend is False]),
    ] + [(f"Sesión {s}", [b for b in bks if b.session == s and not b.weekend]) for s in ("Asia", "Europa", "EEUU", "Tarde")]
    L.append("| Rasgo en la vela de ruptura | Resultado |")
    L.append("|---|---|")
    L += [f"| {label} | {_rate(g)} |" for label, g in rows]
    combo = [b for b in bks if b.vol_ratio <= v_lo and b.wick > 0.3]
    strong = [b for b in bks if b.vol_ratio >= v_hi and b.wick < 0.2 and b.with_trend]
    L.append(f"| **Combinación trampa**: volumen bajo + mecha en contra > 30 % | {_rate(combo)} |")
    L.append(f"| **Combinación real**: volumen alto + cierre en el extremo + a favor de la EMA 50d | {_rate(strong)} |")
    return L


# ------------------------------------------------------------------ en vivo
# Umbrales del estudio (BTC+ETH+SOL 1H): tercios del volumen relativo de las velas de ruptura.
VOL_LOW, VOL_HIGH = 1.73, 3.13


def classify(b: Breakout) -> tuple[str, list[str]]:
    """Perfil de una ruptura según el estudio: 'trampa' (76 % fallaron), 'real' (26 %) o 'dudosa' (52 %)."""
    bad, good = [], []
    if b.excess < 0.002:
        bad += ["cierra apenas fuera", "cierra apenas fuera"]   # la señal más fuerte cuenta doble
    if b.vol_ratio < VOL_LOW:
        bad.append("volumen bajo")
    if b.wick > 0.4:
        bad.append("mecha larga en contra")
    if b.excess > 0.006:
        good.append("cierre claro fuera")
    if b.vol_ratio > VOL_HIGH:
        good.append("volumen alto")
    if b.wick < 0.15:
        good.append("cierra en el extremo")
    if b.with_trend:
        good.append("a favor de la EMA 50d")
    if len(bad) >= 2 and len(good) <= 1:
        return "trampa", sorted(set(bad))
    if len(good) >= 3 and not bad:
        return "real", good
    return "dudosa", sorted(set(bad)) + good


@dataclass
class LiveBreakout:
    b: Breakout
    t: int
    profile: str
    reasons: list[str]
    failed_at: int | None = None     # vela que cerró de vuelta dentro (trampa confirmada)


def recent_breakouts(candles: list[Candle], window: int = 6, lookback: int = 24, hold: int = 6) -> list[LiveBreakout]:
    """Rupturas de las últimas `window` velas cerradas, con su perfil y si ya fallaron."""
    ema50 = ema_series(candles, "1d", 50)
    out: list[LiveBreakout] = []
    start = max(lookback, len(candles) - window - hold)
    for i in range(start, len(candles)):
        win = candles[i - lookback:i]
        hi, lo = max(c.h for c in win), min(c.l for c in win)
        c = candles[i]
        if not (c.c > hi or c.c < lo):
            continue
        up = c.c > hi
        level, opposite = (hi, lo) if up else (lo, hi)
        rng = (c.h - c.l) or 1e-9
        weekend, session = _session(c.t)
        e = ema50[i]
        b = Breakout(i, up, level, opposite, c.v / (statistics.fmean(x.v for x in win) or 1.0),
                     abs(c.c / level - 1), (c.h - c.c) / rng if up else (c.c - c.l) / rng,
                     (hi - lo) / lo, weekend, session, (c.c > e) == up if e else None)
        profile, reasons = classify(b)
        lb = LiveBreakout(b, c.t, profile, reasons)
        for x in candles[i + 1:i + 1 + hold]:
            if (x.c < level) if up else (x.c > level):
                lb.failed_at = x.t
                break
        if i >= len(candles) - window or lb.failed_at:
            out.append(lb)
    return out


def describe(coin: str, lb: LiveBreakout) -> str:
    b = lb.b
    side = "alcista" if b.up else "bajista"
    if lb.failed_at:
        return (f"🪤 {coin}: la ruptura {side} de {b.level:,.1f} FALLÓ — volvió a cerrar dentro del rango "
                f"(llega al otro extremo, {b.opposite:,.1f}, solo ~20 % en 24 h en 1H; 44 % en 4H)")
    icon = {"trampa": "🪤", "real": "✅", "dudosa": "⚖️"}[lb.profile]
    odds = {"trampa": "76 % fallaron", "real": "26 % fallaron", "dudosa": "52 % fallaron"}[lb.profile]
    return (f"{icon} {coin}: ruptura {side} de {b.level:,.1f} con perfil {lb.profile.upper()} "
            f"({', '.join(lb.reasons) or 'sin señales claras'}; históricamente {odds})")
