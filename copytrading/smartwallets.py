"""Validación de billeteras: ¿quién compró en los suelos y vendió en los techos?

Idea de Juan: en vez de fiarse del PnL del mes (que en un mes bajista premia a cualquiera que
estuviera corto), se marcan en el gráfico los suelos y techos reales y se buscan las billeteras
que compraron en los primeros y vendieron en los segundos. Las que lo hacen de forma repetida
son las que merece la pena vigilar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import Fill


@dataclass(frozen=True)
class Event:
    kind: str          # "suelo" | "techo"
    coin: str
    start: int         # ms
    end: int           # ms
    ref_price: float   # mínimo del suelo o máximo del techo

    @classmethod
    def from_dates(cls, kind: str, coin: str, start: str, end: str, ref_price: float) -> "Event":
        ms = lambda s: int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
        return cls(kind, coin, ms(start), ms(end) + 86_400_000 - 1, ref_price)


@dataclass
class EventHit:
    event: Event
    net_usd: float       # compras netas (suelo) o ventas netas (techo), en USD
    avg_px: float
    realized: float      # PnL realizado en la ventana (relevante en techos)
    hit: bool


@dataclass
class WalletScore:
    address: str
    hits: list[EventHit] = field(default_factory=list)
    held: bool = False   # llegó al techo con la posición larga abierta desde el suelo

    @property
    def bottoms(self) -> int:
        return sum(h.hit for h in self.hits if h.event.kind == "suelo")

    @property
    def tops(self) -> int:
        return sum(h.hit for h in self.hits if h.event.kind == "techo")

    @property
    def realized(self) -> float:
        return sum(h.realized for h in self.hits if h.hit)

    @property
    def label(self) -> str:
        if self.bottoms and self.tops:
            return "maestra"
        return "suelo" if self.bottoms else ("techo" if self.tops else "-")

    @property
    def score(self) -> float:
        """Más eventos acertados primero; a igualdad, más PnL realizado."""
        return (self.bottoms + self.tops) * 1e12 + self.realized


def evaluate(address: str, fills: list[Fill], events: list[Event], min_usd: float = 100_000,
             tol: float = 0.06) -> WalletScore:
    ws = WalletScore(address)
    for ev in events:
        win = [f for f in fills if f.coin == ev.coin and ev.start <= f.time <= ev.end]
        buys = [f for f in win if f.side == "B"]
        sells = [f for f in win if f.side == "A"]
        b_usd = sum(f.sz * f.px for f in buys)
        s_usd = sum(f.sz * f.px for f in sells)
        if ev.kind == "suelo":
            net, side = b_usd - s_usd, buys
            avg = b_usd / sum(f.sz for f in buys) if buys else 0.0
            hit = net >= min_usd and avg <= ev.ref_price * (1 + tol)
        else:
            net, side = s_usd - b_usd, sells
            avg = s_usd / sum(f.sz for f in sells) if sells else 0.0
            hit = net >= min_usd and avg >= ev.ref_price * (1 - tol)
        realized = sum(f.closed_pnl - f.fee for f in side)
        ws.hits.append(EventHit(ev, net, avg, realized, hit))

    # ¿mantuvo la posición? posición larga al empezar el techo, abierta durante o antes del suelo
    for ev_top in (e for e in events if e.kind == "techo"):
        first = next((f for f in fills if f.coin == ev_top.coin and f.time >= ev_top.start), None)
        bought = any(h.hit and h.event.kind == "suelo" and h.event.coin == ev_top.coin for h in ws.hits)
        if first and bought and first.start_position > 0:
            ws.held = True
    return ws


def rank(fills_by_wallet: dict[str, list[Fill]], events: list[Event], **kw) -> list[WalletScore]:
    scores = [evaluate(a, sorted(fs, key=lambda f: f.time), events, **kw) for a, fs in fills_by_wallet.items()]
    return sorted((s for s in scores if s.bottoms or s.tops), key=lambda s: s.score, reverse=True)


def swing_events(candles, coin: str, threshold: float = 0.05, half_window_ms: int = 12 * 3_600_000) -> list[Event]:
    """Giros automáticos (zigzag): un techo/suelo cuenta cuando el precio se aleja de él más de `threshold`.

    Cada giro genera un evento con ventana de ±`half_window_ms` alrededor del extremo.
    """
    events: list[Event] = []
    if not candles:
        return events
    mode = None                       # "up" buscando techo, "down" buscando suelo
    ext = candles[0]
    for c in candles[1:]:
        if mode is None:
            if c.h >= candles[0].l * (1 + threshold):
                mode, ext = "up", c
            elif c.l <= candles[0].h * (1 - threshold):
                mode, ext = "down", c
            continue
        if mode == "up":
            if c.h > ext.h:
                ext = c
            elif c.l <= ext.h * (1 - threshold):
                events.append(Event("techo", coin, ext.t - half_window_ms, ext.t + half_window_ms, ext.h))
                mode, ext = "down", c
        else:
            if c.l < ext.l:
                ext = c
            elif c.h >= ext.l * (1 + threshold):
                events.append(Event("suelo", coin, ext.t - half_window_ms, ext.t + half_window_ms, ext.l))
                mode, ext = "up", c
    return events


def hits_minus_errors(address: str, fills: list[Fill], events: list[Event], min_usd: float = 50_000,
                      tol: float = 0.02) -> tuple[int, int]:
    """(aciertos, errores): comprar en suelos / vender en techos frente a lo contrario."""
    inv = [Event("techo" if e.kind == "suelo" else "suelo", e.coin, e.start, e.end, e.ref_price) for e in events]
    h = evaluate(address, fills, events, min_usd=min_usd, tol=tol)
    e = evaluate(address, fills, inv, min_usd=min_usd, tol=0.99)
    return h.bottoms + h.tops, e.bottoms + e.tops
