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
    status: str = "abierta"  # "abierta" | "cerrada"
    r: float = 0.0           # resultado (o resultado latente si sigue abierta)
    exit_reason: str = ""
    exit_time: int = 0


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


def update_outcome(e: JournalEntry, candles: list[Candle], cfg: MethodConfig = VARIANTS["sistema-A"]) -> JournalEntry:
    """Sigue la operación con las velas posteriores a la señal (misma gestión que el backtest)."""
    if e.status == "cerrada":
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
        lines.append(f"{source:10} cerradas {len(closed):3} | aciertos {wins / len(closed) if closed else 0:4.0%} "
                     f"| media {avg:+.2f}R | total {sum(e.r for e in closed):+.2f}R | abiertas {len(es) - len(closed)}")
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
