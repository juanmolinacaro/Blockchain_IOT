"""Semáforo de entradas + cuenta de papel (13 nov 2026).

Juan: "llevamos una semana con el radar; hay que ver que los datos sirvan para decidir, no que queden
guardados". El semáforo junta en UNA forma de decidir solo lo que ha mostrado ventaja medida, y la cuenta
de papel registra sola cada señal con su resultado en R (sin elegir a mano cuáles cuentan).

Setups (velas de 1H cerradas, BTC y ETH):

* **M / W**: doble techo (o suelo) a ±0,2 %, con ≥ 5 velas entre picos y un valle ≥ 0,4 %, el 2.º pico
  con MENOS volumen, a favor de la tendencia; entrada al cierre que rompe el cuello; stop 0,1 % más allá
  del pico más extremo. Estudio: +0,29R/op (38 casos, 1H, BTC+ETH+SOL, ~208 días).
* **Trampa**: la vela barre el máximo (o mínimo) de 24 h y cierra de vuelta dentro; orden límite en el
  nivel barrido (válida 6 velas); stop 0,1 % más allá de la mecha. Estudio: +0,08 a +0,11R/op.
* **Ruptura de compresión**: 12 velas apretadas y cierre fuera a favor de la tendencia; stop al otro lado
  de la caja. Estudio: +0,08R/op (+0,14R con objetivo 1,5R).

Filtro (no medido aún en historia; por eso se registran también las señales que NO lo pasan, para
comparar): confirmación del radar a favor con ≥ 3 votos netos, la tendencia a favor y la mayoría no en
contra. Solo las que pasan el filtro llegan al móvil como "🚦 SEÑAL".

Gestión de Juan: mitad en 1R y stop a la entrada; resto a 2R; cierre por tiempo a las 48 h; comisión
0,09 % ida y vuelta descontada en R.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

PAPER = Path("data/papel.jsonl")
FEE = 0.0009
LIMIT_BARS_MS = 6 * 3_600_000
MAX_HOLD_MS = 48 * 3_600_000


@dataclass
class Signal:
    setup: str
    coin: str
    side: str            # short | long
    entry: float         # precio de entrada (o de la orden límite)
    stop: float
    limit: bool = False  # True = orden límite esperando a que el precio vuelva
    note: str = ""


@dataclass
class Paper:
    id: str
    setup: str
    coin: str
    side: str
    entry: float
    stop: float
    created: int
    filtro: bool
    votos: dict = field(default_factory=dict)
    note: str = ""
    status: str = "pendiente"      # pendiente (límite) | abierta | cerrada | sin llenar
    opened: int = 0
    closed: int = 0
    half: bool = False
    r: float = 0.0
    exit_reason: str = ""

    @property
    def risk(self) -> float:
        return abs(self.stop - self.entry)

    def level(self, mult: float) -> float:
        return self.entry - mult * self.risk if self.side == "short" else self.entry + mult * self.risk


# ------------------------------------------------------------------ detectores (última vela cerrada)
def _pivot(c, j, k, high):
    w = c[j - k:j + k + 1]
    return c[j].h == max(x.h for x in w) if high else c[j].l == min(x.l for x in w)


def detect_mw(c, trend: str, tol=0.002, dip=0.004, k=3, look=40, after=12) -> Signal | None:
    i = len(c) - 1
    if i < look + k + 2:
        return None
    for side in ("short", "long"):
        high = side == "short"
        if trend and trend != ("BAJISTA" if high else "ALCISTA"):
            continue
        pk = [j for j in range(i - look, i - k) if _pivot(c, j, k, high)]
        if len(pk) < 2:
            continue
        p1, p2 = pk[-2], pk[-1]
        if p2 - p1 < 5 or i - p2 > after:
            continue
        v1, v2 = (c[p1].h, c[p2].h) if high else (c[p1].l, c[p2].l)
        if abs(v2 - v1) / v1 > tol:
            continue
        mid = c[p1:p2 + 1]
        neck = min(x.l for x in mid) if high else max(x.h for x in mid)
        depth = (min(v1, v2) - neck) / neck if high else (neck - max(v1, v2)) / neck
        if depth < dip:
            continue
        crossed = (c[i].c < neck <= c[i - 1].c) if high else (c[i].c > neck >= c[i - 1].c)
        if not crossed:
            continue
        weaker = sum(x.v for x in c[p2 - 1:p2 + 2]) < sum(x.v for x in c[p1 - 1:p1 + 2])
        if not weaker:
            continue
        stop = max(v1, v2) * 1.001 if high else min(v1, v2) * 0.999
        return Signal("M/W", "", side, c[i].c, stop,
                      note=f"{'doble techo' if high else 'doble suelo'} {v1:,.0f}/{v2:,.0f}, cuello {neck:,.0f}, 2.º pico más flojo")
    return None


def detect_trap(c, n=24) -> Signal | None:
    i = len(c) - 1
    if i < n + 1:
        return None
    w = c[i - n:i]
    hh, ll = max(x.h for x in w), min(x.l for x in w)
    k = c[i]
    if k.h > hh and k.c < hh:
        return Signal("trampa", "", "short", hh, k.h * 1.001, limit=True,
                      note=f"barrió el máximo de 24 h {hh:,.0f} (mecha {k.h:,.0f}) y cerró dentro")
    if k.l < ll and k.c > ll:
        return Signal("trampa", "", "long", ll, k.l * 0.999, limit=True,
                      note=f"barrió el mínimo de 24 h {ll:,.0f} (mecha {k.l:,.0f}) y cerró dentro")
    return None


def detect_compression(c, trend: str) -> Signal | None:
    from .escucha import compression_break
    card = compression_break(c, trend)
    if not card:
        return None
    lo, hi = card["caja"]
    return Signal("compresión", "", card["lado"], card["entrada"], card["stop"],
                  note=f"rompe la caja de 12 h {lo:,.0f}–{hi:,.0f}")


def detect_all(c, trend: str) -> list[Signal]:
    out = []
    for s in (detect_mw(c, trend), detect_trap(c), detect_compression(c, trend)):
        if s:
            out.append(s)
    return out


def passes_filter(conf: dict, side: str) -> bool:
    sign = -1 if side == "short" else 1
    v = conf.get("votos", {})
    return (conf.get("total", 0) * sign >= 3 and v.get("tendencia", 0) * sign > 0
            and v.get("mayoría", 0) * sign >= 0)


# ------------------------------------------------------------------ cuenta de papel
def load(path: Path = PAPER) -> list[Paper]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(Paper(**json.loads(line)))
        except (ValueError, TypeError):
            continue
    return out


def save(items: list[Paper], path: Path = PAPER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(asdict(p), ensure_ascii=False) + "\n" for p in items), encoding="utf-8")


def open_signal(items: list[Paper], s: Signal, coin: str, now_ms: int, filtro: bool, votos: dict) -> Paper | None:
    """Registra la señal (una por setup, moneda y lado mientras haya otra viva)."""
    if any(p.setup == s.setup and p.coin == coin and p.side == s.side and p.status in ("pendiente", "abierta")
           for p in items):
        return None
    p = Paper(f"{s.setup}-{coin}-{s.side}-{now_ms}", s.setup, coin, s.side, s.entry, s.stop, now_ms, filtro,
              votos, s.note, status="pendiente" if s.limit else "abierta", opened=0 if s.limit else now_ms)
    if p.risk <= 0:
        return None
    items.append(p)
    return p


def update(p: Paper, hi: float, lo: float, now_ms: int) -> str | None:
    """Avanza una operación de papel con el máximo y mínimo del último tramo. Devuelve lo que pasó."""
    short = p.side == "short"
    if p.status == "pendiente":
        if now_ms - p.created > LIMIT_BARS_MS:
            p.status, p.closed, p.exit_reason = "sin llenar", now_ms, "la orden límite caducó"
            return "sin llenar"
        if (hi >= p.entry) if short else (lo <= p.entry):
            p.status, p.opened = "abierta", now_ms
            return "llenada"
        return None
    if p.status != "abierta":
        return None
    fee_r = FEE * p.entry / p.risk
    stop = p.entry if p.half else p.stop
    if (hi >= stop) if short else (lo <= stop):
        p.r = (0.5 if p.half else -1.0) - fee_r
        p.status, p.closed, p.exit_reason = "cerrada", now_ms, "stop en la entrada" if p.half else "stop"
        return p.exit_reason
    if not p.half and ((lo <= p.level(1)) if short else (hi >= p.level(1))):
        p.half = True
        return "TP1 (1R): mitad cerrada, stop a la entrada"
    if p.half and ((lo <= p.level(2)) if short else (hi >= p.level(2))):
        p.r = 1.5 - fee_r
        p.status, p.closed, p.exit_reason = "cerrada", now_ms, "TP2 (2R)"
        return p.exit_reason
    if now_ms - p.opened > MAX_HOLD_MS:
        last = (lo + hi) / 2
        move = (p.entry - last) / p.risk if short else (last - p.entry) / p.risk
        p.r = (0.5 + 0.5 * move if p.half else move) - fee_r
        p.status, p.closed, p.exit_reason = "cerrada", now_ms, "48 h"
        return "cerrada por tiempo"
    return None


def scoreboard(items: list[Paper]) -> list[str]:
    lines = []
    for filtro in (True, False):
        title = "🚦 Con filtro (las que llegan al móvil)" if filtro else "Sin pasar el filtro (solo registro)"
        g = [p for p in items if p.filtro == filtro]
        if not g:
            continue
        lines.append(title)
        for setup in sorted({p.setup for p in g}):
            ps = [p for p in g if p.setup == setup]
            done = [p for p in ps if p.status == "cerrada"]
            live = sum(p.status in ("pendiente", "abierta") for p in ps)
            nofill = sum(p.status == "sin llenar" for p in ps)
            tot = sum(p.r for p in done)
            lines.append(f"  {setup:12} cerradas {len(done):3} · ganadoras {sum(p.r > 0 for p in done):3} · "
                         f"{tot:+.2f}R ({(tot / len(done)) if done else 0:+.2f}R/op) · abiertas {live} · sin llenar {nofill}")
    return lines or ["Cuenta de papel vacía todavía."]
