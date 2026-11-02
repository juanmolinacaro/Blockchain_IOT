"""Imagen del monitor para el móvil: gráfico de 4H con los niveles que importan y 3 líneas de texto.

Idea de Juan: tanto texto y porcentajes confunden sin ver el gráfico. La imagen muestra lo mismo que
él mira en TradingView (velas, canal, EMA 50/200 diarias, liquidez) más los planes del diario, y
arriba un resumen en lenguaje simple: estado (semáforo), qué pasó y qué vigilar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .models import Candle

BG, PANEL, GRID, TXT, MUTED = "#131722", "#1e222d", "#2a2e39", "#d1d4dc", "#787b86"
UP, DOWN = "#26a69a", "#ef5350"
EMA50_C, EMA200_C = "#f23645", "#ff9800"
POOL_LONG, POOL_SHORT = "#7e57c2", "#7e57c2"
STATE_COLORS = {"ENTRADA": "#2962ff", "VIGILAR": "#f9a825", "CALMA": "#4c525e", "FIN DE SEMANA": "#4c525e"}
COT = timezone(timedelta(hours=-5))


@dataclass
class Level:
    price: float
    label: str
    color: str
    style: str = "-"          # "-", "--", ":"
    band: float = 0.0         # medio ancho de banda (precio); 0 = línea


@dataclass
class Summary:
    coin: str
    price: float
    state: str                               # ENTRADA | VIGILAR | CALMA | FIN DE SEMANA
    happened: list[str] = field(default_factory=list)
    watch: list[str] = field(default_factory=list)


def _k(px: float) -> str:
    """Precio corto y legible: 76.766 / 2.257 / 93,5."""
    if px >= 1000:
        return f"{px:,.0f}".replace(",", ".")
    return f"{px:,.1f}".replace(".", ",")


def plan_name(note: str) -> str:
    m = re.match(r"\s*([A-Z]\d?)\s*:", note or "")
    return f"Plan {m.group(1)}" if m else "Plan"


def plan_levels(entries, coin: str) -> list[Level]:
    out = []
    for e in entries:
        if e.coin != coin or e.status not in ("pendiente", "abierta"):
            continue
        name = plan_name(e.note)
        tag = (name[5:] + " ") if name != "Plan" else ""
        verb = "venta" if e.side == "short" else "compra"
        if e.status == "pendiente":
            cond = {"below": "si <", "above": "si >", "touch_below": "en", "touch_above": "en"}.get(
                e.trigger_dir, "")
            out.append(Level(e.trigger, f"{tag}{verb} {cond} {_k(e.trigger)}", "#ffeb3b", "--"))
        else:
            out.append(Level(e.entry, f"{tag}{verb} en {_k(e.entry)}", "#ffeb3b", "-"))
        out.append(Level(e.stop, f"{tag}stop {_k(e.stop)}", DOWN, ":"))
        out.append(Level(e.tp2, f"{tag}obj. {_k(e.tp2)}", UP, ":"))
    return out


def render(path: str, candles: list[Candle], summary: Summary, levels: list[Level],
           channel=None, ema50: list[float | None] | None = None, ema200: list[float | None] | None = None,
           bars: int = 42) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle

    n0 = max(0, len(candles) - bars)
    view = candles[n0:]
    xs = range(len(view))
    pad_right = 17                                   # hueco a la derecha para las etiquetas

    fig = plt.figure(figsize=(7.2, 9.0), dpi=150, facecolor=BG)
    # --- cabecera: moneda, precio, semáforo y 2 bloques de texto
    fig.text(0.04, 0.955, summary.coin, color=TXT, fontsize=26, fontweight="bold", va="center")
    fig.text(0.04 + 0.035 * len(summary.coin) + 0.03, 0.955, _k(summary.price), color=TXT, fontsize=22, va="center")
    col = STATE_COLORS.get(summary.state, "#4c525e")
    fig.patches.append(FancyBboxPatch((0.66, 0.935), 0.30, 0.042, boxstyle="round,pad=0.006,rounding_size=0.012",
                                      transform=fig.transFigure, facecolor=col, edgecolor="none"))
    fig.text(0.81, 0.956, summary.state, color="white", fontsize=15, fontweight="bold", ha="center", va="center")
    y = 0.905
    for title, lines in (("Qué pasó", summary.happened), ("Qué vigilar", summary.watch)):
        fig.text(0.04, y, title.upper(), color=MUTED, fontsize=10, fontweight="bold", va="center")
        y -= 0.028
        for ln in (lines or ["nada nuevo"])[:3]:
            fig.text(0.05, y, "• " + ln, color=TXT, fontsize=12.5, va="center")
            y -= 0.03
        y -= 0.008
    top = y - 0.01

    ax = fig.add_axes((0.02, 0.05, 0.96, top - 0.05), facecolor=BG)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.yaxis.tick_right()
    ax.grid(color=GRID, linewidth=0.6)

    lo = min(c.l for c in view)
    hi = max(c.h for c in view)
    px = view[-1].c
    shown = [lv for lv in levels if abs(lv.price / px - 1) <= 0.07]
    for lv in shown:
        lo, hi = min(lo, lv.price - lv.band), max(hi, lv.price + lv.band)
    span = hi - lo
    ax.set_ylim(lo - span * 0.04, hi + span * 0.04)
    ax.set_xlim(-1, len(view) + pad_right)

    # velas
    w = 0.62
    for x, c in zip(xs, view):
        colr = UP if c.c >= c.o else DOWN
        ax.vlines(x, c.l, c.h, color=colr, linewidth=1.0, zorder=3)
        ax.add_patch(Rectangle((x - w / 2, min(c.o, c.c)), w, max(abs(c.c - c.o), span * 0.002),
                               facecolor=colr, edgecolor=colr, zorder=4))
    # canal vigente (proyectado sobre la ventana)
    if channel is not None:
        gx = [x for x in xs]
        idx = [n0 + x for x in gx]
        ax.plot(gx, [channel.upper(i) for i in idx], color="white", linewidth=1.3, alpha=0.85, zorder=2)
        ax.plot(gx, [channel.lower(i) for i in idx], color="white", linewidth=1.3, alpha=0.85, zorder=2)
    # EMAs diarias
    for series, colr, name in ((ema50, EMA50_C, "EMA 50d"), (ema200, EMA200_C, "EMA 200d")):
        if series:
            vals = series[n0:]
            pts = [(x, v) for x, v in zip(xs, vals) if v]
            if pts:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], color=colr, linewidth=2.0, zorder=2)
                shown.append(Level(pts[-1][1], f"{name} {_k(pts[-1][1])}", colr, "none"))
    # precio actual: una etiqueta más, para que no se monte sobre las otras
    ax.axhline(px, color="white", linestyle=(0, (1, 2)), linewidth=0.9, alpha=0.7)
    shown.append(Level(px, f"ahora {_k(px)}", "white", "none"))
    # niveles con etiqueta a la derecha (sin solaparse)
    ymin, ymax = ax.get_ylim()
    min_gap = (ymax - ymin) * 0.035
    placed: list[float] = []
    for lv in sorted(shown, key=lambda v: -v.price):
        if lv.band:
            ax.axhspan(lv.price - lv.band, lv.price + lv.band, color=lv.color, alpha=0.28, zorder=1, linewidth=0)
        elif lv.style != "none":
            ax.axhline(lv.price, color=lv.color, linestyle=lv.style, linewidth=1.4, alpha=0.95, zorder=2)
        ty = lv.price
        for p in placed:
            if abs(ty - p) < min_gap:
                ty = p - min_gap
        placed.append(ty)
        ax.text(len(view) + 0.6, ty, lv.label, color=lv.color, fontsize=9.5, va="center", fontweight="bold",
                zorder=6, bbox=dict(facecolor=BG, edgecolor="none", pad=1.2, alpha=0.85))
    # eje X: días
    ticks, labels = [], []
    for x, c in zip(xs, view):
        d = datetime.fromtimestamp(c.t / 1000, COT)
        if d.hour < 4:
            ticks.append(x)
            labels.append(d.strftime("%a %d").replace("Mon", "lun").replace("Tue", "mar").replace("Wed", "mié")
                          .replace("Thu", "jue").replace("Fri", "vie").replace("Sat", "sáb").replace("Sun", "dom"))
    ax.set_xticks(ticks, labels)
    ax.set_yticks([])
    fig.text(0.04, 0.018, "Velas de 4H · hora Colombia · líneas blancas: canal · morado: liquidez estimada",
             color=MUTED, fontsize=8)
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path


def build(coin: str, candles: list[Candle], candles_1h: list[Candle], entries, now_ms: int,
          events: list[str] | None = None, recent_hours: float = 8) -> tuple[Summary, list[Level], dict]:
    """Resumen en lenguaje simple + niveles para la imagen de una moneda (velas de 4H cerradas)."""
    from .method.backtest import compute_channels, compute_liquidity
    from .method.emas import ema_series
    from .method.monitor import VARIANTS, analyze, trading_allowed
    from .method.traps import recent_breakouts

    st = analyze(coin, candles)
    px = candles_1h[-1].c if candles_1h else candles[-1].c
    happened = list(events or [])
    latest = {}
    for lb in recent_breakouts(candles_1h, window=int(recent_hours)):
        if (lb.failed_at or lb.t) >= now_ms - recent_hours * 3_600_000:
            latest[lb.b.up] = lb                  # solo la última ruptura de cada lado
    for lb in latest.values():
        side = "arriba" if lb.b.up else "abajo"
        if lb.failed_at:
            happened.append(f"Rompió hacia {side} ({_k(lb.b.level)}) pero volvió dentro: trampa")
        else:
            verdict = {"trampa": "parece TRAMPA", "real": "parece REAL", "dudosa": "aún dudosa"}[lb.profile]
            happened.append(f"Rompió hacia {side} ({_k(lb.b.level)}): {verdict}")
    channels = compute_channels(candles, VARIANTS["sistema-A"])
    ch = channels[-1]
    if not happened and ch is not None:
        i = len(candles) - 1
        lo, up = ch.lower(i), ch.upper(i)
        pos = ("cerca del techo" if px > up - (up - lo) * 0.2 else
               "cerca del piso" if px < lo + (up - lo) * 0.2 else "en medio")
        happened.append(f"Precio {pos} del canal ({_k(lo)} – {_k(up)})")

    watch, levels = [], plan_levels(entries, coin)
    for e in entries:
        if e.coin != coin or e.status not in ("pendiente", "abierta"):
            continue
        name, verb = plan_name(e.note), ("venta" if e.side == "short" else "compra")
        if e.status == "abierta":
            watch.append(f"{name} en curso ({verb} {_k(e.entry)}): stop {_k(e.stop)} · objetivo {_k(e.tp2)}")
        else:
            tf = e.interval.upper()
            cond = {"below": f"cierre {tf} bajo", "above": f"cierre {tf} sobre", "touch_below": "toque de",
                    "touch_above": "toque de"}.get(e.trigger_dir, "")
            watch.append(f"{name}: {verb} con {cond} {_k(e.trigger)}")
    # zonas con más liquidez estimada (como las franjas del heatmap) y hacia dónde tira el imán
    liq = compute_liquidity(candles, VARIANTS["sistema-A"])[-1]
    for lpx, name in ((liq.best_long_px, "liquidez largos"), (liq.best_short_px, "liquidez cortos")):
        if lpx:
            levels.append(Level(lpx, f"{name} {_k(lpx)}", POOL_LONG, band=lpx * 0.003))
    if liq.best_long_px and liq.best_short_px:
        if liq.long_below >= 1.5 * liq.short_above:
            watch.append(f"Imán: más liquidez abajo, en {_k(liq.best_long_px)}")
        elif liq.short_above >= 1.5 * liq.long_below:
            watch.append(f"Imán: más liquidez arriba, en {_k(liq.best_short_px)}")
        else:
            watch.append(f"Liquidez repartida: {_k(liq.best_long_px)} abajo / {_k(liq.best_short_px)} arriba")

    activated = any("ACTIVADO" in ev or "SEÑAL" in ev for ev in happened)
    near_trigger = any(e.coin == coin and e.status == "pendiente" and abs(e.trigger / px - 1) < 0.01 for e in entries)
    if not trading_allowed(now_ms):
        state = "FIN DE SEMANA"
    elif activated or st.status == "SEÑAL":
        state = "ENTRADA"
    elif st.status == "VIGILAR" or near_trigger or len(happened) > 1 or "Rompió" in " ".join(happened):
        state = "VIGILAR"
    else:
        state = "CALMA"
    extra = dict(channel=ch, ema50=ema_series(candles, "1d", 50), ema200=ema_series(candles, "1d", 200))
    return Summary(coin, px, state, happened, watch), levels, extra


def coin_image(path: str, coin: str, candles: list[Candle], candles_1h: list[Candle], entries, now_ms: int,
               events: list[str] | None = None) -> tuple[str, Summary]:
    summary, levels, extra = build(coin, candles, candles_1h, entries, now_ms, events)
    # la última vela de 4H en curso se dibuja con el precio de 1H para que el gráfico esté al día
    view = list(candles)
    if candles_1h and candles_1h[-1].t >= view[-1].t + 4 * 3_600_000:
        part = [c for c in candles_1h if c.t >= view[-1].t + 4 * 3_600_000]
        view.append(Candle(part[0].t, part[0].o, max(c.h for c in part), min(c.l for c in part), part[-1].c,
                           sum(c.v for c in part)))
        for k in ("ema50", "ema200"):
            extra[k] = list(extra[k]) + [extra[k][-1]]
    render(path, view, summary, levels, **extra)
    return path, summary
