"""¿Aciertan los avisos de la escucha? Mide cada aviso de `hft_eventos.jsonl` con el precio posterior.

Para cada aviso se mira el precio (velas de 1 minuto de Hyperliquid) 15 y 60 minutos después:

* **empuje** (💰 las cuentas que ganan / 🤖 los cazadores COMPRAN o VENDEN): acierta si el precio va en la
  dirección del empuje;
* **retiro** de un solo lado (🏦 retiran compras → camino libre abajo; retiran ventas → arriba): acierta
  si el precio va hacia el lado vaciado;
* **retiro de los dos lados a la vez**: no dice dirección. Se mide si después hay más movimiento que lo
  normal (la media del movimiento de 15 minutos en todo el periodo);
* **💥 liquidaciones de Binance**: se mide si el barrido sigue (continuación) o rebota.

Un caso no es una señal: el informe dice cuántos avisos de cada tipo hay y el acierto con su número.
"""
from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

COT = timezone(timedelta(hours=-5))
HORIZONS = (15, 60)
PAIR_S = 10          # retiros de compras y ventas a menos de 10 s: "los dos lados"


@dataclass
class Medida:
    t: int
    moneda: str
    clase: str            # empuje-ganadoras, empuje-cazadores, retiro-un-lado, retiro-ambos, liq-binance
    esperado: int         # +1 sube, −1 baja, 0 sin dirección
    precio: float
    cambios: dict         # minutos -> cambio relativo
    titulo: str

    def acierto(self, h: int) -> bool | None:
        c = self.cambios.get(h)
        if c is None or self.esperado == 0:
            return None
        return c * self.esperado > 0


def load_events(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return sorted(out, key=lambda e: e["t"])


def classify(events: list[dict]) -> list[tuple[dict, str, int]]:
    """(evento, clase, dirección esperada). Junta los retiros de compras y ventas simultáneos."""
    out = []
    retiros = [e for e in events if e["tipo"].startswith("retiro-")]
    used: set[int] = set()
    for e in events:
        tipo = e["tipo"]
        if tipo.startswith("empuje-"):
            grupo = "ganadoras" if e.get("grupo") == "ganadoras" or "ganan" in e.get("titulo", "") else "cazadores"
            out.append((e, f"empuje-{grupo}", 1 if tipo.endswith("COMPRAN") else -1))
        elif tipo.startswith("liq-binance-"):
            out.append((e, "liq-binance", -1 if tipo.endswith("largos") else 1))     # dirección del barrido
        elif tipo.startswith("retiro-") and id(e) not in used:
            twin = next((o for o in retiros if o is not e and id(o) not in used and o["moneda"] == e["moneda"]
                         and o["lado"] != e["lado"] and abs(o["t"] - e["t"]) <= PAIR_S * 1000), None)
            if twin is not None:
                used.update({id(e), id(twin)})
                out.append((e, "retiro-ambos", 0))
            else:
                used.add(id(e))
                out.append((e, "retiro-un-lado", -1 if e["lado"] == "compras" else 1))
    return out


def price_after(times: list[int], closes: list[float], t_ms: int, minutes: int) -> float | None:
    target = t_ms + minutes * 60_000
    i = bisect_right(times, target) - 1
    if i < 0 or target - times[i] > 2 * 60_000:
        return None
    return closes[i]


def measure(events: list[dict], candles: dict[str, list]) -> list[Medida]:
    """`candles`: moneda -> velas de 1 m (con .t inicio en ms y .c cierre)."""
    series = {c: ([k.t + 60_000 for k in cs], [k.c for k in cs]) for c, cs in candles.items()}   # hora de cierre
    out = []
    for e, clase, esperado in classify(events):
        times, closes = series.get(e["moneda"], ([], []))
        base = price_after(times, closes, e["t"], 0) or e["precio"]
        cambios = {}
        for h in HORIZONS:
            p = price_after(times, closes, e["t"], h)
            if p is not None and base:
                cambios[h] = p / base - 1
        out.append(Medida(e["t"], e["moneda"], clase, esperado, base, cambios, e.get("titulo", "")))
    return out


def typical_move(candles: list, minutes: int = 15) -> float:
    """Movimiento absoluto medio en `minutes` minutos (referencia para los retiros de los dos lados)."""
    closes = [k.c for k in candles]
    moves = [abs(closes[i + minutes] / closes[i] - 1) for i in range(0, len(closes) - minutes, minutes)]
    return sum(moves) / len(moves) if moves else 0.0


NAMES = {"empuje-ganadoras": "💰 empuje de las cuentas que ganan", "empuje-cazadores": "🤖 empuje de los cazadores",
         "retiro-un-lado": "🏦 retiro de un solo lado", "retiro-ambos": "🏦 retiro de los dos lados a la vez",
         "liq-binance": "💥 liquidaciones de Binance (¿sigue el barrido?)"}


def report(medidas: list[Medida], typical: dict[str, float]) -> list[str]:
    lines = [f"{'aviso (hora Colombia)':51}  {'precio':>9}  {'15 min':>8}  {'60 min':>8}  acierto 15/60"]
    for m in medidas:
        when = datetime.fromtimestamp(m.t / 1000, COT).strftime("%a %d %H:%M")
        c15, c60 = (m.cambios.get(h) for h in HORIZONS)
        f = lambda c: "     —" if c is None else f"{c * 100:+7.2f}%"
        hit = lambda h: {True: "sí", False: "no", None: "—"}[m.acierto(h)]
        lines.append(f"{when} {m.moneda:3} {NAMES[m.clase][:34]:34}  {m.precio:>9,.1f}  {f(c15):>8}  {f(c60):>8}  "
                     f"{hit(15)}/{hit(60)}")
    lines.append("")
    for clase, name in NAMES.items():
        ms = [m for m in medidas if m.clase == clase]
        if not ms:
            continue
        if clase == "retiro-ambos":
            big = [m for m in ms if m.cambios.get(15) is not None
                   and abs(m.cambios[15]) > 1.5 * typical.get(m.moneda, 1)]
            done = [m for m in ms if m.cambios.get(15) is not None]
            normal = ", ".join(f"{c} {v * 100:.2f} %" for c, v in sorted(typical.items()))
            lines.append(f"{name}: {len(ms)} avisos · {len(big)} de {len(done)} con movimiento > 1,5× lo normal "
                         f"en 15 min (lo normal: {normal})")
            continue
        parts = []
        for h in HORIZONS:
            done = [m for m in ms if m.acierto(h) is not None]
            ok = sum(m.acierto(h) for m in done)
            parts.append(f"{h} min {ok}/{len(done)}" + (f" ({ok / len(done) * 100:.0f} %)" if done else ""))
        lines.append(f"{name}: {len(ms)} avisos · acierto " + " · ".join(parts))
    lines.append("Pocos casos todavía: con menos de ~20 avisos de un tipo, el porcentaje no es fiable.")
    return lines
