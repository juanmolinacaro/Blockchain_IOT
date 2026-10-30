"""Mapa de liquidez (liquidaciones) construido con posiciones reales on-chain.

En Hyperliquid cada posición publica su precio de liquidación exacto. Sumando
el tamaño de las posiciones de muchas wallets por franja de precio se obtiene
dónde está "cargado" el mercado:

  * por DEBAJO del precio se acumulan liquidaciones de LONGS,
  * por ENCIMA del precio se acumulan liquidaciones de SHORTS.

El precio tiende a buscar esas zonas (las liquidaciones son órdenes a mercado
forzadas que alimentan el movimiento). Colores:
  rojo = franjas más cargadas (percentil >= 80), amarillo (>= 50), verde (resto).
"""
from __future__ import annotations

import html
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .sources.base import DataSource

log = logging.getLogger(__name__)

RED, YELLOW, GREEN = "rojo", "amarillo", "verde"
COLORS = {RED: "#e5484d", YELLOW: "#f5c518", GREEN: "#30a46c"}


@dataclass(frozen=True)
class LiqPoint:
    coin: str
    is_long: bool
    liquidation_px: float
    size: float       # en monedas, positivo


@dataclass
class Band:
    low: float
    high: float
    long_usd: float = 0.0   # longs que se liquidan en esta franja
    short_usd: float = 0.0  # shorts que se liquidan en esta franja
    level: str = ""
    n: int = 0              # número de posiciones
    largest_usd: float = 0.0

    @property
    def whale_share(self) -> float:
        """Fracción de la franja que corresponde a una sola posición."""
        return self.largest_usd / self.total if self.total else 0.0

    @property
    def total(self) -> float:
        return self.long_usd + self.short_usd

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2


@dataclass
class Heatmap:
    coin: str
    price: float
    bands: list[Band] = field(default_factory=list)
    n_positions: int = 0

    def zones(self, level: str = RED) -> list[Band]:
        return [b for b in self.bands if b.level == level]

    def nearest(self, above: bool, level: str = RED) -> Band | None:
        cands = [b for b in self.zones(level) if (b.low > self.price if above else b.high < self.price)]
        return min(cands, key=lambda b: abs(b.mid - self.price), default=None)

    @property
    def usd_above(self) -> float:
        return sum(b.total for b in self.bands if b.low > self.price)

    @property
    def usd_below(self) -> float:
        return sum(b.total for b in self.bands if b.high < self.price)


# --------------------------------------------------------------- recolección
def collect_liquidations(source: DataSource, addresses: Iterable[str], coin: str | None = None,
                         pause_s: float = 0.05,
                         on_progress: Callable[[int], None] | None = None) -> list[LiqPoint]:
    points: list[LiqPoint] = []
    for i, addr in enumerate(addresses, 1):
        try:
            st = source.account_state(addr)
        except Exception as exc:
            log.debug("No se pudo leer %s: %s", addr, exc)
            continue
        for pos in st.positions.values():
            if (coin and pos.coin != coin) or not pos.liquidation_px:
                continue
            points.append(LiqPoint(pos.coin, pos.size > 0, pos.liquidation_px, abs(pos.size)))
        if on_progress:
            on_progress(i)
        if pause_s:
            time.sleep(pause_s)  # respeta el rate limit de la API
    return points


def wallets_to_scan(source: DataSource, top: int) -> list[str]:
    """Las `top` cuentas con más capital del leaderboard: concentran la mayor parte del interés abierto."""
    rows = sorted(source.leaderboard(), key=lambda r: r.account_value, reverse=True)
    return [r.address for r in rows[:top]]


# ------------------------------------------------------------------ mapa
def build_heatmap(points: list[LiqPoint], coin: str, price: float,
                  range_pct: float = 0.15, band_pct: float = 0.005) -> Heatmap:
    lo, hi = price * (1 - range_pct), price * (1 + range_pct)
    width = price * band_pct
    n = max(1, round((hi - lo) / width))
    bands = [Band(lo + i * width, lo + (i + 1) * width) for i in range(n)]
    used = 0
    for p in points:
        if p.coin != coin or not lo <= p.liquidation_px < hi:
            continue
        b = bands[min(int((p.liquidation_px - lo) / width), n - 1)]
        usd = p.size * price
        b.n += 1
        b.largest_usd = max(b.largest_usd, usd)
        if p.is_long:
            b.long_usd += usd
        else:
            b.short_usd += usd
        used += 1
    classify(bands)
    return Heatmap(coin, price, bands, used)


def classify(bands: list[Band]) -> None:
    totals = sorted(b.total for b in bands if b.total > 0)
    if not totals:
        return
    p50, p80 = _percentile(totals, 0.5), _percentile(totals, 0.8)
    for b in bands:
        if b.total <= 0:
            b.level = ""
        elif b.total >= p80:
            b.level = RED
        elif b.total >= p50:
            b.level = YELLOW
        else:
            b.level = GREEN


def _percentile(sorted_vals: list[float], q: float) -> float:
    idx = q * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


# --------------------------------------------------------- interpretación
def insights(hm: Heatmap) -> list[str]:
    """Lectura en lenguaje natural del mapa, para apoyar decisiones (no son señales garantizadas)."""
    out: list[str] = []
    if not hm.n_positions:
        return [f"No hay posiciones con liquidación dentro del rango para {hm.coin}."]
    for above in (False, True):
        lado = "arriba" if above else "abajo"
        b = hm.nearest(above)
        etiqueta = "Zona ROJA más cercana"
        if not b:  # sin zona roja en este lado: se informa la franja más cargada
            side = [x for x in hm.bands if x.total > 0 and (x.low > hm.price if above else x.high < hm.price)]
            if not side:
                continue
            b = max(side, key=lambda x: x.total)
            etiqueta = f"Zona más cargada ({b.level.upper()})"
        dist = (b.mid - hm.price) / hm.price
        quien = "shorts" if above else "longs"
        whale = (f" Ojo: el {b.whale_share:.0%} es UNA sola posición (ballena)."
                 if b.whale_share >= 0.6 else "")
        out.append(f"{etiqueta} {lado}: {_fmt(b.low)}–{_fmt(b.high)} "
                   f"({dist:+.1%}), ${b.total:,.0f} en liquidaciones de {quien} "
                   f"({b.n} posiciones).{whale}")
    up, down = hm.usd_above, hm.usd_below
    if up or down:
        if not down:
            out.append("Toda la liquidez del rango está arriba (shorts): sesgo de 'imán' alcista.")
        elif not up:
            out.append("Toda la liquidez del rango está abajo (longs): sesgo de 'imán' bajista.")
        elif up / down > 1.5:
            out.append(f"Hay {up / down:.1f}x más liquidez arriba (shorts): sesgo de 'imán' alcista.")
        elif down / up > 1.5:
            out.append(f"Hay {down / up:.1f}x más liquidez abajo (longs): sesgo de 'imán' bajista.")
        else:
            out.append("Liquidez equilibrada arriba y abajo: sin sesgo claro.")
    out.append("Uso sugerido: zonas rojas como objetivos de toma de ganancias y para no poner el stop "
               "justo dentro de ellas; evitar abrir en contra de una zona roja muy cercana (riesgo de barrido).")
    return out


def _fmt(px: float) -> str:
    return f"{px:,.2f}" if px >= 1 else f"{px:.6g}"


# ---------------------------------------------------------------- salida
def render_text(hm: Heatmap, width: int = 40) -> str:
    peak = max((b.total for b in hm.bands), default=0) or 1
    icons = {RED: "🟥", YELLOW: "🟨", GREEN: "🟩", "": "  "}
    lines = [f"Mapa de liquidaciones {hm.coin} — precio {_fmt(hm.price)} — {hm.n_positions} posiciones"]
    marked = False
    for b in reversed(hm.bands):
        if not marked and b.high <= hm.price:
            lines.append(f"{'─' * 12} precio actual {_fmt(hm.price)} {'─' * 12}")
            marked = True
        if b.total <= 0:
            continue
        bar = "█" * max(1, round(b.total / peak * width))
        whale = " 🐋" if b.whale_share >= 0.6 else ""
        lines.append(f"{icons[b.level]} {_fmt(b.low):>12} – {_fmt(b.high):<12} {bar} ${b.total:,.0f}"
                     f" ({b.n}){whale}")
    return "\n".join(lines + [""] + ["• " + s for s in insights(hm)])


def render_html(hm: Heatmap, generated_at: str = "") -> str:
    rows = [b for b in reversed(hm.bands)]
    peak = max((b.total for b in rows), default=0) or 1
    row_h, label_w, bar_w = 14, 190, 520
    svg_h = row_h * len(rows) + 10
    parts = []
    for i, b in enumerate(rows):
        y = i * row_h + 5
        if b.total > 0:
            w = max(2, b.total / peak * bar_w)
            parts.append(f'<rect x="{label_w}" y="{y}" width="{w:.1f}" height="{row_h - 2}" '
                         f'fill="{COLORS[b.level]}"><title>{_fmt(b.low)}–{_fmt(b.high)}: '
                         f'longs ${b.long_usd:,.0f} / shorts ${b.short_usd:,.0f}</title></rect>')
        if i % 4 == 0:
            parts.append(f'<text x="{label_w - 8}" y="{y + row_h - 4}" text-anchor="end">{_fmt(b.mid)}</text>')
    y_price = next((i for i, b in enumerate(rows) if b.high <= hm.price), len(rows)) * row_h + 5
    parts.append(f'<line x1="{label_w}" x2="{label_w + bar_w}" y1="{y_price}" y2="{y_price}" class="px"/>'
                 f'<text x="{label_w + bar_w}" y="{y_price - 3}" text-anchor="end" class="px-t">'
                 f'precio {_fmt(hm.price)}</text>')
    items = "".join(f"<li>{html.escape(s)}</li>" for s in insights(hm))
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Liquidez {html.escape(hm.coin)}</title>
<style>
:root {{ --bg:#fff; --fg:#1c1c1c; --muted:#666; --line:#1c1c1c; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141414; --fg:#eee; --muted:#999; --line:#eee; }} }}
body {{ background:var(--bg); color:var(--fg); font:14px system-ui,sans-serif; margin:0 auto; max-width:760px; padding:16px; }}
svg {{ width:100%; height:auto; }} svg text {{ fill:var(--muted); font-size:10px; }}
.px {{ stroke:var(--line); stroke-dasharray:4 3; }} .px-t {{ fill:var(--fg); font-weight:600; }}
.legend span {{ display:inline-block; width:10px; height:10px; margin:0 4px 0 12px; border-radius:2px; }}
p.muted {{ color:var(--muted); }}
</style></head><body>
<h1>Mapa de liquidaciones · {html.escape(hm.coin)}</h1>
<p class="muted">{html.escape(generated_at)} · {hm.n_positions} posiciones reales de Hyperliquid ·
arriba del precio = shorts, abajo = longs</p>
<p class="legend"><span style="background:{COLORS[RED]}"></span>rojo: más cargado
<span style="background:{COLORS[YELLOW]}"></span>amarillo <span style="background:{COLORS[GREEN]}"></span>verde</p>
<svg viewBox="0 0 {label_w + bar_w + 10} {svg_h}" role="img" aria-label="Mapa de liquidaciones">{''.join(parts)}</svg>
<h2>Lectura</h2><ul>{items}</ul>
<p class="muted">Información para apoyar decisiones; no garantiza la dirección del precio.</p>
</body></html>"""
