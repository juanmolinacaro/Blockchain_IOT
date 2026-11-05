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


@dataclass
class Position:
    """Como la herramienta Posición larga/corta de TradingView: verde = objetivo, rojo = stop."""
    side: str            # "long" | "short"
    entry: float
    stop: float
    tp1: float
    tp2: float
    start_t: int         # vela desde la que se dibuja (entrada o creación del plan)
    name: str            # "D", "C" o ""
    pending: bool        # aún no activado: se dibuja más tenue
    cond: str = ""       # "si cierra 4H < 77.250"
    runner: bool = False # sin TP2: asegura en TP1 y deja correr

    @property
    def rr(self) -> float:
        return abs(self.tp2 - self.entry) / abs(self.entry - self.stop) if self.entry != self.stop else 0.0


def plan_positions(entries, coin: str) -> list[Position]:
    out = []
    for e in entries:
        if e.coin != coin or e.status not in ("pendiente", "abierta"):
            continue
        name = plan_name(e.note)[5:]
        pending = e.status == "pendiente"
        entry = e.trigger if pending else e.entry
        cond = ""
        if pending:
            tf = e.interval.upper()
            cond = {"below": f"si cierra {tf} < {_k(e.trigger)}", "above": f"si cierra {tf} > {_k(e.trigger)}",
                    "touch_below": f"orden en {_k(e.trigger)}", "touch_above": f"orden en {_k(e.trigger)}"
                    }.get(e.trigger_dir, "")
            if getattr(e, "sweep", 0):
                cond = f"tras barrer {_k(e.sweep)}, {cond}"
        out.append(Position(e.side, entry, e.stop, e.tp1, e.tp2 or e.tp1, e.time, name, pending, cond,
                            runner=not e.tp2))
    return out


def _draw_position(ax, pos: Position, x0: float, x1: float, fs: float = 8.5) -> None:
    from matplotlib.patches import Rectangle
    a = 0.2 if pos.pending else 0.26
    green, red = "#089981", "#f23645"
    ax.add_patch(Rectangle((x0, min(pos.entry, pos.tp2)), x1 - x0, abs(pos.tp2 - pos.entry),
                           facecolor=green, alpha=a, edgecolor=green, linewidth=0.8, zorder=1.5))
    ax.add_patch(Rectangle((x0, min(pos.entry, pos.stop)), x1 - x0, abs(pos.stop - pos.entry),
                           facecolor=red, alpha=a, edgecolor=red, linewidth=0.8, zorder=1.5))
    ax.hlines(pos.entry, x0, x1, color="#d1d4dc", linewidth=1.2, linestyles="--" if pos.pending else "-", zorder=2.5)
    if pos.tp1 != pos.tp2:
        ax.hlines(pos.tp1, x0, x1, color=green, linewidth=0.9, linestyles=":", zorder=2.5)
    verb = "Venta" if pos.side == "short" else "Compra"
    tag = f" {pos.name}" if pos.name else ""
    pct = lambda p: f"{(p / pos.entry - 1) * 100:+.1f} %".replace(".", ",")
    box = dict(facecolor="#131722", edgecolor="none", pad=1.0, alpha=0.75)
    head = f"{verb}{tag} {_k(pos.entry)}" + (" (pendiente)" if pos.pending else "")
    ax.text(x0 + 0.3, pos.entry, head + f" · R/R {pos.rr:.1f}".replace(".", ","), color="white", fontsize=fs,
            va="bottom" if pos.side == "long" else "top", fontweight="bold", zorder=7, bbox=box)
    ax.text(x0 + 0.3, pos.tp2, f"Objetivo {_k(pos.tp2)} ({pct(pos.tp2)})" + (" → asegurar y dejar correr" if pos.runner else ""),
            color="#4caf50", fontsize=fs,
            va="top" if pos.side == "long" else "bottom", fontweight="bold", zorder=7, bbox=box)
    ax.text(x0 + 0.3, pos.stop, f"Stop {_k(pos.stop)} ({pct(pos.stop)})", color="#ff6b6b", fontsize=fs,
            va="bottom" if pos.side == "long" else "top", fontweight="bold", zorder=7, bbox=box)


def render(path: str, candles: list[Candle], summary: Summary, levels: list[Level],
           channel=None, ema50: list[float | None] | None = None, ema200: list[float | None] | None = None,
           bars: int = 42, positions: list[Position] | None = None) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle

    n0 = max(0, len(candles) - bars)
    view = candles[n0:]
    xs = range(len(view))
    pad_right = 24                                   # hueco a la derecha: cajas de posición + etiquetas
    label_x = len(view) + 8.0

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
    for pos in positions or []:
        if abs(pos.entry / px - 1) <= 0.07:
            lo, hi = min(lo, pos.stop, pos.tp2, pos.entry), max(hi, pos.stop, pos.tp2, pos.entry)
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
    # posiciones del diario (cajas verde/roja como en TradingView)
    for pos in positions or []:
        if abs(pos.entry / px - 1) > 0.07:
            continue
        if pos.pending:                       # aún no activado: caja propia a la derecha de la última vela
            x0 = len(view) - 0.2
        else:
            x0 = next((x for x, c in zip(xs, view) if c.t >= pos.start_t), 0) - 0.4
        _draw_position(ax, pos, max(-0.8, x0), len(view) + (7.4 if pos.pending else -0.4))
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
        if not ymin <= lv.price <= ymax:          # fuera del gráfico (p. ej. una EMA lejana): sin etiqueta
            continue
        if lv.band:
            ax.axhspan(lv.price - lv.band, lv.price + lv.band, color=lv.color, alpha=0.22, zorder=1, linewidth=0)
        elif lv.style != "none":
            ax.axhline(lv.price, color=lv.color, linestyle=lv.style, linewidth=1.4, alpha=0.95, zorder=2)
        ty = lv.price
        for p in placed:
            if abs(ty - p) < min_gap:
                ty = p - min_gap
        placed.append(ty)
        ax.text(label_x, ty, lv.label, color=lv.color, fontsize=9.5, va="center", fontweight="bold",
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
    fig.text(0.04, 0.018, "Velas 4H · hora Colombia · blanco: canal · morado: liquidez · lila: 100x recientes · naranja: ballenas",
             color=MUTED, fontsize=8)
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return path


def _warnings(side: str, magnet: str, bias: str | None, trend: str = "") -> str:
    """Avisos de un plan: contra el imán de liquidez y (BTC) contra las billeteras de tendencia.
    Estudio 4 nov 2026 (BTC): operar el imán en contra de las billeteras de tendencia dio -0,32R."""
    out = ""
    if (side == "long" and trend == "BAJISTA") or (side == "short" and trend == "ALCISTA"):
        out += " ⚠ CONTRA LA TENDENCIA"
    if (side == "long" and magnet == "abajo") or (side == "short" and magnet == "arriba"):
        out += " ⚠ CONTRA EL IMÁN"
    if (side == "long" and bias == "BAJISTA") or (side == "short" and bias == "ALCISTA"):
        out += " ⚠ CONTRA LAS BILLETERAS"
    return out


def build(coin: str, candles: list[Candle], candles_1h: list[Candle], entries, now_ms: int,
          events: list[str] | None = None, recent_hours: float = 8, st=None,
          whales=None, bias: str | None = None) -> tuple[Summary, list[Level], dict]:
    """Resumen en lenguaje simple + niveles para la imagen de una moneda (velas de 4H cerradas)."""
    from .method.backtest import compute_channels, compute_liquidity
    from .method.emas import ema_series
    from .method.monitor import VARIANTS, analyze, nearest_pools, trading_allowed, trend_state
    from .method.traps import recent_breakouts

    analysis = analyze(coin, candles)
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

    watch, levels = [], []
    trend, _, slope = trend_state(candles)
    liq = compute_liquidity(candles, VARIANTS["sistema-A"])[-1]
    magnet = ("abajo" if liq.long_below >= 1.5 * liq.short_above else
              "arriba" if liq.short_above >= 1.5 * liq.long_below else "")
    for e in entries:
        if e.coin != coin or e.status not in ("pendiente", "abierta"):
            continue
        name, verb = plan_name(e.note), ("venta" if e.side == "short" else "compra")
        if e.status == "abierta":
            warn = _warnings(e.side, magnet, bias if coin == "BTC" else None, trend)
            goal = f"objetivo {_k(e.tp2)}" if e.tp2 else f"asegura en {_k(e.tp1)} y deja correr"
            watch.append(f"{name} en curso ({verb} {_k(e.entry)}): stop {_k(e.stop)} · {goal}{warn}")
        else:
            tf = e.interval.upper()
            cond = {"below": f"cierre {tf} bajo", "above": f"cierre {tf} sobre", "touch_below": "toque de",
                    "touch_above": "toque de"}.get(e.trigger_dir, "")
            pre = f"tras barrer {_k(e.sweep)}, " if getattr(e, "sweep", 0) else ""
            warn = _warnings(e.side, magnet, bias if coin == "BTC" else None, trend)
            watch.append(f"{name}: {verb} {pre}con {cond} {_k(e.trigger)}{warn}")
    # zonas con más liquidez estimada (como las franjas del heatmap) y hacia dónde tira el imán
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
    # imán fuerte: un pool >= 2x el del otro lado (4H: el precio llegó antes al grande 8 de cada 10 veces)
    strong = False
    below, above = nearest_pools(candles)
    if below and above:
        big, small, where = (below, above, "abajo") if below.size >= above.size else (above, below, "arriba")
        if big.size >= 2 * small.size:
            strong = True
            levels.append(Level(big.center, f"IMÁN {_k(big.center)}", "#e040fb", band=big.center * 0.004))
            watch.insert(0, f"IMÁN FUERTE {where} en {_k(big.center)} ({big.size / small.size:.1f}x): operar solo hacia él")
    # capa de corto plazo (25-100x, últimos días) y liquidaciones reales de ballenas
    for z in st or []:
        kind = "cortos" if z.side == "short" else "largos"
        levels.append(Level(z.center, f"{kind} 100x {_k(z.center)}", "#b39ddb", band=z.center * 0.0015))
    for z in whales or []:
        levels.append(Level(z.mid, f"ballena ${z.usd / 1e6:,.0f}M {_k(z.mid)}", "#ff9800", band=(z.high - z.low) / 2))
        kind = "largos" if z.side == "long" else "cortos"
        watch.append(f"Ballena: ${z.usd / 1e6:,.0f}M de {kind} se liquidan en {_k(z.mid)}")

    if trend in ("ALCISTA", "BAJISTA"):
        watch.insert(0, f"Tendencia {trend} (EMA 50 diaria {slope:+.1%} en 6 días): "
                        f"buscar solo {'largos' if trend == 'ALCISTA' else 'cortos'}".replace(".", ",", 1))
    activated = any("ACTIVADO" in ev or "SEÑAL" in ev for ev in happened)
    near_trigger = any(e.coin == coin and e.status == "pendiente" and abs(e.trigger / px - 1) < 0.01 for e in entries)
    if not trading_allowed(now_ms):
        state = "FIN DE SEMANA"
    elif activated or analysis.status == "SEÑAL":
        state = "ENTRADA"
    elif (analysis.status == "VIGILAR" or near_trigger or strong or len(happened) > 1
          or "Rompió" in " ".join(happened)):
        state = "VIGILAR"
    else:
        state = "CALMA"
    extra = dict(channel=ch, ema50=ema_series(candles, "1d", 50), ema200=ema_series(candles, "1d", 200),
                 positions=plan_positions(entries, coin))
    return Summary(coin, px, state, happened, watch), levels, extra


def coin_image(path: str, coin: str, candles: list[Candle], candles_1h: list[Candle], entries, now_ms: int,
               events: list[str] | None = None, st=None, whales=None, bias: str | None = None) -> tuple[str, Summary]:
    summary, levels, extra = build(coin, candles, candles_1h, entries, now_ms, events, st=st, whales=whales,
                                   bias=bias)
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
