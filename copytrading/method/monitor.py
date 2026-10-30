"""Monitor en vivo del método + diario de señales.

Cada ejecución (pensada para cada cierre de vela de 4H):
  1. Analiza la última vela CERRADA de cada moneda con dos variantes del sistema:
       A = canal + liquidez + confluencia con la EMA 50/200 diaria
       B = canal + liquidez + filtro de la EMA 200 diaria
  2. Marca "VIGILAR" cuando el precio se acerca a un borde del canal que coincide con
     una EMA diaria o con liquidez fuerte al otro lado.
  3. Apunta las señales nuevas en el diario (JSONL) y actualiza el resultado de las
     abiertas, tanto del sistema como las que Juan añade a mano.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..models import Candle
from .backtest import MethodConfig, Trade, compute_channels, compute_liquidity, find_signal, manage
from .emas import compute_emas, ema_series, parse_spec
from .liqmodel import LiquidationModel
from .pools import _zones, config_for

BAR_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

VARIANTS = {
    "sistema-A": MethodConfig(stop_mode="close", trend="channel", ema="1d:50,1d:200", ema_mode="confluence"),
    "sistema-B": MethodConfig(stop_mode="close", trend="channel", ema="1d:200", ema_mode="filter"),
}


@dataclass
class CoinStatus:
    coin: str
    time: int
    price: float
    status: str = "-"                       # "SEÑAL" | "VIGILAR" | "-"
    signals: dict[str, Trade] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class JournalEntry:
    id: str
    source: str              # "sistema-A" | "sistema-B" | "juan"
    coin: str
    interval: str
    side: str
    time: int                # vela de la señal (ms)
    entry: float
    stop: float
    tp1: float
    tp2: float
    note: str = ""
    status: str = "abierta"  # "pendiente" | "abierta" | "cerrada" | "caducada" | "anulada"
    r: float = 0.0           # resultado (o resultado latente si sigue abierta)
    exit_reason: str = ""
    exit_time: int = 0
    # planes condicionados: se activan cuando una vela CIERRA más allá de `trigger`
    trigger: float = 0.0
    trigger_dir: str = ""    # "below"/"above": cierre más allá | "touch_below"/"touch_above": orden límite
    expires: int = 0         # ms; si no se activa antes, caduca


def closed_candles(candles: list[Candle], interval: str, now_ms: int | None = None) -> list[Candle]:
    """Quita la vela en curso: solo se decide con velas cerradas."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    bar = BAR_MS[interval]
    return [c for c in candles if c.t + bar <= now_ms]


def analyze(coin: str, candles: list[Candle], watch_pct: float = 0.015,
            conf_pct: float = 0.02) -> CoinStatus:
    i = len(candles) - 1
    st = CoinStatus(coin, candles[i].t, candles[i].c)
    base = VARIANTS["sistema-A"]
    liq = compute_liquidity(candles, base)
    channels = compute_channels(candles, base)
    for name, cfg in VARIANTS.items():
        t = find_signal(candles, i, cfg, liq, channels, compute_emas(candles, cfg.ema))
        if t:
            st.signals[name] = t
    if st.signals:
        st.status = "SEÑAL"

    ch = channels[i]
    px = candles[i].c
    emas = {f"EMA{n} {tf}": ema_series(candles, tf, n)[i] for tf, n in parse_spec("1d:50,1d:200")}
    s = liq[i]
    if ch is None:
        st.notes.append("Sin canal vigente")
        return st
    lower, upper = ch.lower(i), ch.upper(i)
    st.notes.append(f"Canal {ch.shape()}: {lower:,.1f} – {ch.mid(i):,.1f} – {upper:,.1f}")
    for name, e in emas.items():
        if e:
            st.notes.append(f"{name}: {e:,.1f} ({px / e - 1:+.1%})")
    st.notes.append(f"Liquidez estimada: más cargado abajo {s.best_long_px:,.1f}, arriba {s.best_short_px:,.1f} "
                    f"(longs/shorts {s.long_below:.0f}/{s.short_above:.0f})")
    st.notes.extend(magnet_notes(candles))
    if st.status == "SEÑAL":
        return st

    for border, side, liq_px in ((lower, "inferior", s.best_long_px), (upper, "superior", s.best_short_px)):
        if abs(px - border) / px > watch_pct:
            continue
        reasons = [n for n, e in emas.items() if e and abs(e - border) / border <= conf_pct]
        if liq_px and abs(liq_px - border) / border <= conf_pct * 1.5:
            reasons.append(f"liquidez en {liq_px:,.1f}")
        if reasons:
            st.status = "VIGILAR"
            st.notes.append(f"Precio a {abs(px - border) / px:.1%} del borde {side} ({border:,.1f}) "
                            f"con confluencia: {', '.join(reasons)}")
    return st


def magnet_notes(candles: list[Candle]) -> list[str]:
    """Pools (picos del mapa) más cercanos arriba y abajo, y cuál domina como imán.

    Estudio histórico (BTC+ETH+SOL, 30 oct 2026): el precio toca antes el pool más cercano ~75 %
    de las veces; cuando un pool es >=2x mayor que el del otro lado, va primero al grande el 66 %
    (1H) - 88 % (4H) de las veces.
    """
    bar_h = (candles[1].t - candles[0].t) / 3_600_000
    sc = config_for(bar_h)
    model = LiquidationModel(decay_per_bar=0.5 ** (1 / sc.half_life_bars))
    usd = []
    for c in candles:
        model.update(c)
        usd.append(c.v * c.c)
    win = usd[-sc.vol_window:]
    avg = sum(win) / len(win) or 1.0
    px = candles[-1].c
    below = [z for z in _zones(model, "long", px, avg, sc) if z.center < px]
    above = [z for z in _zones(model, "short", px, avg, sc) if z.center > px]
    if not below and not above:
        return ["Pools: ninguno relevante a ±10 %"]
    if not below or not above:
        where = "abajo" if below else "arriba"
        z = max(below, key=lambda q: q.center) if below else min(above, key=lambda q: q.center)
        return [f"Pools: solo hay pool relevante {where}, en {z.center:,.1f} ({abs(z.center / px - 1):.1%}, "
                f"tamaño {z.size:.0f}) → imán de un solo lado"]
    b = max(below, key=lambda z: z.center)
    a = min(above, key=lambda z: z.center)
    out = [f"Pools: abajo {b.center:,.1f} ({px / b.center - 1:.1%}, tamaño {b.size:.0f}) · "
           f"arriba {a.center:,.1f} ({a.center / px - 1:.1%}, tamaño {a.size:.0f})"]
    big, small, where = (b, a, "abajo") if b.size >= a.size else (a, b, "arriba")
    if big.size >= 2 * small.size:
        out.append(f"Imán dominante {where}: pool {big.size / small.size:.1f}x mayor "
                   "(histórico: va primero al grande ~2 de cada 3 veces en 1H, ~9 de cada 10 en 4H)")
    else:
        closer = "abajo" if px / b.center - 1 < a.center / px - 1 else "arriba"
        out.append(f"Sin imán dominante: lo más probable es tocar antes el más cercano ({closer}, ~75 % histórico)")
    return out


# ------------------------------------------------------------------- diario
def load_journal(path: Path) -> list[JournalEntry]:
    if not path.exists():
        return []
    return [JournalEntry(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line]


def save_journal(path: Path, entries: list[JournalEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(e), ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")


def record_signals(entries: list[JournalEntry], st: CoinStatus, interval: str) -> list[JournalEntry]:
    known = {e.id for e in entries}
    new = []
    for source, t in st.signals.items():
        eid = f"{source}-{st.coin}-{st.time}"
        if eid not in known:
            new.append(JournalEntry(eid, source, st.coin, interval, t.side, st.time,
                                    t.entry, t.stop, t.tp1, t.tp2))
    entries.extend(new)
    return new


def activate_plan(e: JournalEntry, candles: list[Candle]) -> JournalEntry:
    """Un plan pendiente se abre al cierre de la primera vela que cruza su nivel de activación."""
    for c in candles:
        if c.t < e.time:
            continue
        if e.expires and c.t >= e.expires:
            e.status = "caducada"
            return e
        if e.trigger_dir.startswith("touch"):
            filled = c.l <= e.trigger if e.trigger_dir == "touch_below" else c.h >= e.trigger
            ran_away = c.h >= e.tp1 if e.side == "long" else c.l <= e.tp1
            if not filled and ran_away:   # se fue al objetivo sin retroceder: no se habría entrado
                e.status, e.exit_reason = "anulada", "llegó al TP1 sin retroceder a la entrada"
                return e
            crossed, fill_px = filled, e.trigger
        else:
            crossed = c.c < e.trigger if e.trigger_dir == "below" else c.c > e.trigger
            fill_px = c.c
        if crossed:
            e.time, e.entry = c.t, fill_px
            valid = (e.stop > e.entry > e.tp1 >= e.tp2) if e.side == "short" else (e.stop < e.entry < e.tp1 <= e.tp2)
            e.status = "abierta" if valid else "anulada"
            if not valid:
                e.exit_reason = "el cierre de activación quedó más allá del stop o del objetivo"
            return e
    if e.expires and candles and candles[-1].t + (candles[-1].t - candles[-2].t if len(candles) > 1 else 0) >= e.expires:
        e.status = "caducada"
    return e


def update_outcome(e: JournalEntry, candles: list[Candle], cfg: MethodConfig = VARIANTS["sistema-A"]) -> JournalEntry:
    """Sigue la operación con las velas posteriores a la señal (misma gestión que el backtest)."""
    if e.status == "pendiente":
        activate_plan(e, candles)
    if e.status != "abierta":
        return e
    idx = next((k for k, c in enumerate(candles) if c.t >= e.time), None)
    if idx is None:
        return e
    if candles[idx].t > e.time:   # entrada manual entre velas: se toma la vela anterior como referencia
        idx = max(idx - 1, 0)
    trade = manage(Trade(e.side, idx, e.entry, e.stop, e.tp1, e.tp2), candles, cfg)
    still_running = trade.exit_reason == "tiempo" and idx + cfg.max_bars > len(candles) - 1
    e.r = round(trade.r, 3)
    if not still_running and trade.exit_i > idx:
        e.status, e.exit_reason, e.exit_time = "cerrada", trade.exit_reason, candles[trade.exit_i].t
    return e


def summary(entries: list[JournalEntry]) -> list[str]:
    lines = []
    for source in sorted({e.source for e in entries}):
        es = [e for e in entries if e.source == source]
        closed = [e for e in es if e.status == "cerrada"]
        wins = sum(e.r > 0 for e in closed)
        avg = sum(e.r for e in closed) / len(closed) if closed else 0.0
        opened = sum(e.status == "abierta" for e in es)
        pending = sum(e.status == "pendiente" for e in es)
        lines.append(f"{source:10} cerradas {len(closed):3} | aciertos {wins / len(closed) if closed else 0:4.0%} "
                     f"| media {avg:+.2f}R | total {sum(e.r for e in closed):+.2f}R | abiertas {opened}"
                     + (f" | planes pendientes {pending}" if pending else ""))
    return lines or ["Diario vacío."]


def manual_entry(coin: str, side: str, entry: float, stop: float, tp1: float, tp2: float,
                 note: str = "", interval: str = "4h", now_ms: int | None = None) -> JournalEntry:
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if side == "long" and not stop < entry < tp1 <= tp2:
        raise ValueError("Para un largo: stop < entrada < TP1 <= TP2")
    if side == "short" and not stop > entry > tp1 >= tp2:
        raise ValueError("Para un corto: stop > entrada > TP1 >= TP2")
    return JournalEntry(f"juan-{coin}-{now_ms}", "juan", coin, interval, side, now_ms,
                        entry, stop, tp1, tp2, note)


def manual_plan(coin: str, side: str, trigger: float, trigger_dir: str, stop: float, tp1: float, tp2: float,
                hours: float = 48, note: str = "", interval: str = "1h",
                now_ms: int | None = None) -> JournalEntry:
    """Plan condicionado: se abre solo si una vela de `interval` cierra más allá de `trigger`."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if trigger_dir not in ("below", "above", "touch_below", "touch_above"):
        raise ValueError("trigger_dir debe ser below, above, touch_below o touch_above")
    if side == "short" and not stop > trigger > tp1 >= tp2:
        raise ValueError("Para un corto: stop > activación > TP1 >= TP2")
    if side == "long" and not stop < trigger < tp1 <= tp2:
        raise ValueError("Para un largo: stop < activación < TP1 <= TP2")
    return JournalEntry(f"juan-{coin}-{side}-{now_ms}", "juan", coin, interval, side, now_ms,
                        trigger, stop, tp1, tp2, note, status="pendiente", trigger=trigger,
                        trigger_dir=trigger_dir, expires=now_ms + int(hours * 3_600_000))
