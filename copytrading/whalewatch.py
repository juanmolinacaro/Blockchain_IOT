"""Seguimiento de ballenas concretas para usarlas como indicador (también al revés).

Idea de Juan (4 nov 2026): la ballena de los $40M (0xf081…) promedia a la baja y vende en pérdidas
cuando el margen aprieta. Si se equivoca de forma repetida, sus movimientos sirven como indicador
contrario. Aquí se reconstruyen sus "episodios" (rachas de fills en la misma dirección) y qué hizo
el precio después, y se guarda el historial para medirlo con el tiempo.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import Candle, Fill

WATCHLIST = Path("data/ballenas_seguidas.json")
HISTORY = Path("data/ballenas_historial.jsonl")


@dataclass
class Episode:
    address: str
    coin: str
    direction: str     # "Open Long", "Close Long", "Open Short", "Close Short"
    start: int
    end: int
    size: float
    usd: float
    avg_px: float
    pnl: float         # PnL realizado (cierres), neto de comisiones

    @property
    def opens(self) -> bool:
        return self.direction.startswith("Open")

    @property
    def is_long(self) -> bool:
        return self.direction.endswith("Long")


def episodes(address: str, fills: list[Fill], gap_ms: int = 2 * 3_600_000, min_usd: float = 1_000_000) -> list[Episode]:
    """Agrupa fills seguidos (misma moneda y dirección, sin pausas > gap) en episodios."""
    out: list[Episode] = []
    cur: dict[str, Episode] = {}
    for f in sorted(fills, key=lambda f: f.time):
        e = cur.get(f.coin)
        if e and e.direction == f.direction and f.time - e.end <= gap_ms:
            e.size += f.sz
            e.usd += f.sz * f.px
            e.end = f.time
            e.pnl += f.closed_pnl - f.fee
            e.avg_px = e.usd / e.size
        else:
            e = Episode(address, f.coin, f.direction, f.time, f.time, f.sz, f.sz * f.px, f.px, f.closed_pnl - f.fee)
            cur[f.coin] = e
            out.append(e)
    return [e for e in out if e.usd >= min_usd]


def forward_move(candles: list[Candle], t: int, hours: int) -> float | None:
    """Cambio del precio desde t hasta t + hours (None si aún no ha pasado ese tiempo)."""
    before = [c for c in candles if c.t <= t]
    after = [c for c in candles if c.t <= t + hours * 3_600_000]
    if not before or not after or after[-1].t < t + (hours - 1) * 3_600_000:
        return None
    return after[-1].c / before[-1].c - 1


def score(eps: list[Episode], candles_by_coin: dict[str, list[Candle]], hours: int = 72) -> dict:
    """¿Acierta o se equivoca? Para cada apertura: ¿el precio fue a su favor en `hours`?
    Para cada cierre en pérdidas (capitulación): ¿el precio rebotó después (vendió en el suelo)?"""
    opens_right = opens_wrong = caps_bottom = caps_total = 0
    for e in eps:
        cs = candles_by_coin.get(e.coin)
        if not cs:
            continue
        mv = forward_move(cs, e.end, hours)
        if mv is None:
            continue
        if e.opens:
            good = mv > 0 if e.is_long else mv < 0
            opens_right += good
            opens_wrong += not good
        elif e.pnl < 0:
            caps_total += 1
            caps_bottom += (mv > 0) if e.is_long else (mv < 0)   # vendió y luego subió = vendió en el suelo
    return {"aperturas_acertadas": opens_right, "aperturas_falladas": opens_wrong,
            "capitulaciones": caps_total, "capitulaciones_en_suelo": caps_bottom}


def load_watchlist(path: Path = WATCHLIST) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def append_history(eps: list[Episode], path: Path = HISTORY) -> int:
    """Guarda los episodios nuevos (idempotente). Devuelve cuántos se añadieron."""
    known = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            known.add((d["address"], d["coin"], d["direction"], d["start"]))
    new = [e for e in eps if (e.address, e.coin, e.direction, e.start) not in known]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for e in new:
                fh.write(json.dumps(asdict(e)) + "\n")
    return len(new)


def describe(alias: str, e: Episode) -> str:
    """Frase para el aviso, con la lectura contraria."""
    side = "largo" if e.is_long else "corto"
    usd = f"${e.usd / 1e6:,.0f}M"
    if e.opens:
        hint = "si sigue fallando, el precio suele ir en contra"
        return f"🐋 {alias}: abrió/aumentó {side} {usd} a {e.avg_px:,.0f} ({hint})"
    if e.pnl < 0:
        return (f"🐋 {alias}: cerró {side} {usd} a {e.avg_px:,.0f} con pérdida ${-e.pnl / 1e6:,.1f}M "
                "(capitulación: suele ocurrir cerca de un suelo/techo)")
    return f"🐋 {alias}: cerró {side} {usd} a {e.avg_px:,.0f} con ganancia ${e.pnl / 1e6:,.1f}M"
