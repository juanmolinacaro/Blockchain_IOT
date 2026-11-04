"""Indicador de billeteras: hacia dónde apuntan las billeteras validadas.

* Tendencia (giros grandes, ballenas que compraron suelos y vendieron techos): indicador de fondo.
  Si la mayoría está larga, confirma estructura alcista (buscar largos a largo plazo); si está
  corta, los rebotes son tácticos.
* Corto plazo (giros pequeños en 1H): solo informativo, para ver el movimiento inmediato.

Cada grupo de billeteras cuenta como un voto (las que parecen el mismo operador, uno solo), para
que una ballena enorme no decida el indicador por sí sola.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .sources.base import DataSource

LABELS = ((0.34, "ALCISTA"), (-0.34, "BAJISTA"))


@dataclass
class Bias:
    coin: str
    longs: int = 0
    shorts: int = 0
    flat: int = 0
    usd_long: float = 0.0
    usd_short: float = 0.0
    long_names: list = None
    short_names: list = None

    @property
    def score(self) -> float:
        n = self.longs + self.shorts
        return (self.longs - self.shorts) / n if n else 0.0

    @property
    def label(self) -> str:
        if self.longs + self.shorts == 0:
            return "SIN POSICIONES"
        if self.score >= LABELS[0][0]:
            return "ALCISTA"
        if self.score <= LABELS[1][0]:
            return "BAJISTA"
        return "MIXTO"

    def line(self) -> str:
        out = (f"{self.coin}: {self.label} ({self.longs} largos ${self.usd_long / 1e6:.1f}M · "
               f"{self.shorts} cortos ${self.usd_short / 1e6:.1f}M · {self.flat} sin posición)")
        if self.long_names:
            out += f"\n      largos: {', '.join(self.long_names)}"
        if self.short_names:
            out += f"\n      cortos: {', '.join(self.short_names)}"
        return out


def load_lists(path: str | Path = "data/indicador_billeteras.json") -> dict[str, list[dict]]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def compute(source: DataSource, wallets: list[dict], coins=("BTC", "ETH"), mids: dict | None = None,
            pause_s: float = 0.05) -> dict[str, Bias]:
    mids = mids or source.mid_prices()
    out = {c: Bias(c, long_names=[], short_names=[]) for c in coins}
    groups: dict[str, dict[str, float]] = {}            # grupo -> moneda -> tamaño firmado (USD)
    names: dict[str, str] = {}                          # grupo -> alias (las gemelas, uno solo)
    for w in wallets:
        try:
            st = source.account_state(w["address"])
        except Exception:
            continue
        gid = w.get("grupo", w["address"])
        g = groups.setdefault(gid, {})
        names.setdefault(gid, (w.get("alias") or w["address"][:8]).rsplit(" ", 1)[0]
                         if " " in (w.get("alias") or "") and (w.get("alias") or "").split()[-1].isdigit()
                         else (w.get("alias") or w["address"][:8]))
        for c in coins:
            p = st.positions.get(c)
            if p:
                g[c] = g.get(c, 0.0) + p.size * mids.get(c, p.entry_px)
        if pause_s:
            time.sleep(pause_s)
    for gid, g in groups.items():
        for c in coins:
            usd = g.get(c, 0.0)
            b = out[c]
            if usd > 0:
                b.longs, b.usd_long = b.longs + 1, b.usd_long + usd
                b.long_names.append(names[gid])
            elif usd < 0:
                b.shorts, b.usd_short = b.shorts + 1, b.usd_short - usd
                b.short_names.append(names[gid])
            else:
                b.flat += 1
    return out


def report(source: DataSource, path: str | Path = "data/indicador_billeteras.json") -> list[str]:
    lists = load_lists(path)
    if not lists:
        return []
    mids = source.mid_prices()
    lines = ["🐋 Billeteras de tendencia (indicador de fondo):"]
    lines += ["  " + b.line() for b in compute(source, lists.get("tendencia", []), mids=mids).values()]
    lines.append("⚡ Billeteras de corto plazo (solo informativo):")
    lines += ["  " + b.line() for b in compute(source, lists.get("corto_plazo", []), mids=mids).values()]
    return lines
