"""Biblioteca de episodios del escáner: ¿qué hacen las cuentas ANTES de cada tipo de movimiento?

Idea de Juan (9 nov 2026): "se está gestando un movimiento; necesitamos datos de lo que hacen en estos
casos. Ya tenemos datos de caídas; hacen falta acumulaciones antes de subir o bajar, subidas fuertes…".

Con los datos por minuto de la escucha (`hft_flujo*.csv` y `binance_minuto.csv`) se detectan solos:

* **subida fuerte / caída fuerte**: BTC se mueve ≥ 1 % en menos de 60 minutos;
* **compresión → ruptura arriba / abajo / sin ruptura**: 60 minutos con un rango < 0,4 % (el precio se
  aprieta, como el triángulo del 9 nov) y lo que pasa en las 2 horas siguientes (el primero que se aleja
  0,7 % marca la ruptura).

Para cada episodio se mide qué pasó en los **30 minutos anteriores**: empuje neto de las cuentas que
ganan, de los cazadores, de los creadores y del resto; cómo cambió la liquidez de los creadores a cada
lado (frente a su media de la hora previa); y en Binance, el cambio del interés abierto, el empuje
agresivo neto, las liquidaciones y la proporción largos/cortos de todas las cuentas.

Con semanas de datos, cada tipo junta sus casos y se ve qué se repite antes de cada movimiento.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean

COT = timezone(timedelta(hours=-5))
MOVE = 0.01            # movimiento fuerte: ≥ 1 % …
MOVE_WINDOW = 60       # … en menos de 60 min
SQUEEZE_RANGE = 0.004  # compresión: rango de 60 min < 0,4 %
SQUEEZE_WINDOW = 60
BREAK = 0.007          # ruptura: el precio se aleja 0,7 % …
BREAK_WINDOW = 120     # … en las 2 horas siguientes
BEFORE = 30            # minutos que se miran antes del episodio


def _f(row: dict, key: str) -> float | None:
    v = row.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _when(s: str) -> datetime:
    return datetime.strptime(s.strip()[:16], "%Y-%m-%d %H:%M").replace(tzinfo=COT)


def read_minutes(files: list[Path], coin: str = "BTC") -> dict[datetime, dict]:
    """Une varios CSV por minuto (el más reciente manda si hay minutos repetidos)."""
    out: dict[datetime, dict] = {}
    for p in files:
        if not p.exists():
            continue
        with p.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("moneda") == coin and row.get("hora_col"):
                    out[_when(row["hora_col"])] = row
    return out


@dataclass
class Episodio:
    tipo: str                       # subida fuerte, caída fuerte, compresión→arriba, compresión→abajo, compresión→nada
    inicio: datetime
    precio: float
    cambio: float                   # del movimiento (o de la ruptura)
    antes: dict = field(default_factory=dict)


def detect(prices: list[tuple[datetime, float]]) -> list[tuple[str, int, int, float]]:
    """(tipo, índice de inicio, índice de fin, cambio). Movimientos fuertes y compresiones con su salida."""
    from .causa import find_moves
    out = []
    taken: list[tuple[datetime, datetime]] = []
    moves: list[tuple[int, int]] = []
    last_end: dict[str, datetime] = {}
    for i, j in find_moves(prices, MOVE, MOVE_WINDOW):
        ch = prices[j][1] / prices[i][1] - 1
        tipo = "subida fuerte" if ch > 0 else "caída fuerte"
        opuesto = "caída fuerte" if ch > 0 else "subida fuerte"
        if opuesto in last_end and prices[i][0] - last_end[opuesto] <= timedelta(minutes=BEFORE):
            tipo = "rebote tras caída" if ch > 0 else "recaída tras subida"     # reacción, no movimiento propio
        out.append((tipo, i, j, ch))

        last_end["subida fuerte" if ch > 0 else "caída fuerte"] = prices[j][0]
        moves.append((i, j))
        taken.append((prices[i][0] + timedelta(minutes=5), prices[j][0]))     # la compresión previa sí cuenta
    i, n = 0, len(prices)
    while i < n:
        t = prices[i][0]
        win = [p for tt, p in prices[max(0, i - SQUEEZE_WINDOW):i + 1] if t - tt <= timedelta(minutes=SQUEEZE_WINDOW)]
        full = i >= SQUEEZE_WINDOW and prices[i - SQUEEZE_WINDOW][0] >= t - timedelta(minutes=SQUEEZE_WINDOW + 5)
        if not full or max(win) / min(win) - 1 >= SQUEEZE_RANGE or any(a <= t <= b for a, b in taken):
            i += 1
            continue
        # sigue apretado: avanzar mientras el rango total desde el inicio siga < SQUEEZE_RANGE
        lo, hi, k = min(win), max(win), i
        while k + 1 < n and prices[k + 1][0] - prices[k][0] <= timedelta(minutes=5):
            p = prices[k + 1][1]
            if max(hi, p) / min(lo, p) - 1 >= SQUEEZE_RANGE:
                break
            lo, hi, k = min(lo, p), max(hi, p), k + 1
        p0 = prices[k][1]
        tipo, end, ch = "compresión→nada", k, 0.0
        for m in range(k + 1, n):
            if prices[m][0] - prices[k][0] > timedelta(minutes=BREAK_WINDOW):
                break
            c = prices[m][1] / p0 - 1
            if abs(c) >= BREAK:
                tipo, end, ch = ("compresión→arriba" if c > 0 else "compresión→abajo"), m, c
                break
        if not any(a < i <= b for a, b in moves):       # empieza en mitad de un movimiento fuerte: no es compresión
            out.append((tipo, k, end, ch))
        taken.append((prices[i][0], prices[end][0]))
        i = end + 1
    return sorted(out, key=lambda x: prices[x[1]][0])


def _sum(rows: list[dict], a: str, b: str) -> float | None:
    vals = [(_f(r, a), _f(r, b)) for r in rows]
    vals = [(x, y) for x, y in vals if x is not None and y is not None]
    return sum(x - y for x, y in vals) if vals else None


def features(t0: datetime, flow: dict[datetime, dict], binance: dict[datetime, dict]) -> dict:
    """Lo que pasó en los BEFORE minutos anteriores a `t0`."""
    pre = [flow[t] for t in sorted(flow) if t0 - timedelta(minutes=BEFORE) <= t < t0]
    base = [flow[t] for t in sorted(flow) if t0 - timedelta(minutes=BEFORE + 60) <= t < t0 - timedelta(minutes=BEFORE)]
    f: dict = {}
    for name, a, b in (("ganadoras", "ganadoras_compra", "ganadoras_venta"), ("cazadores", "cazador_compra", "cazador_venta"),
                       ("creadores", "creador_compra", "creador_venta"), ("resto", "otros_compra", "otros_venta")):
        f[f"{name}_neto"] = _sum(pre, a, b)
    for side, key in (("compras", "liq_creadores_compra_1pct"), ("ventas", "liq_creadores_venta_1pct")):
        now = [v for v in (_f(r, key) for r in pre[-5:]) if v is not None]
        ref = [v for v in (_f(r, key) for r in base) if v is not None]
        f[f"libro_{side}"] = (fmean(now) / fmean(ref)) if now and ref and fmean(ref) > 0 else None
    bpre = [binance[t] for t in sorted(binance) if t0 - timedelta(minutes=BEFORE) <= t < t0]
    if len(bpre) >= 2:
        oi0, oi1 = _f(bpre[0], "interes_abierto"), _f(bpre[-1], "interes_abierto")
        f["oi_cambio"] = (oi1 / oi0 - 1) if oi0 and oi1 else None
        f["binance_agresivo_neto"] = _sum(bpre, "compra_agresiva_usd", "venta_agresiva_usd")
        f["liq_largos"] = sum(_f(r, "liq_largos_usd") or 0 for r in bpre)
        f["liq_cortos"] = sum(_f(r, "liq_cortos_usd") or 0 for r in bpre)
        l0, l1 = _f(bpre[0], "cuentas_largos_cortos"), _f(bpre[-1], "cuentas_largos_cortos")
        f["cuentas_lc_cambio"] = (l1 - l0) if l0 is not None and l1 is not None else None
    return f


def build(flow_files: list[Path], binance_files: list[Path]) -> list[Episodio]:
    flow = read_minutes(flow_files)
    binance = read_minutes(binance_files)
    prices = [(t, p) for t, r in sorted(flow.items()) if (p := _f(r, "precio"))]
    if not prices:
        prices = [(t, p) for t, r in sorted(binance.items()) if (p := _f(r, "precio"))]
    out = []
    for tipo, i, j, ch in detect(prices):
        t0 = prices[i][0]
        out.append(Episodio(tipo, t0, prices[i][1], ch, features(t0, flow, binance)))
    return out


def _m(v: float | None, kind: str = "usd") -> str:
    if v is None:
        return "—"
    if kind == "usd":
        return f"{'+' if v >= 0 else '−'}${abs(v) / 1e6:.1f}M"
    if kind == "pct":
        return f"{v * 100:+.2f}%"
    if kind == "x":
        return f"×{v:.2f}"
    return f"{v:+.2f}"


ORDER = ("caída fuerte", "subida fuerte", "rebote tras caída", "recaída tras subida", "compresión→arriba",
         "compresión→abajo", "compresión→nada")
COLS = (("ganadoras_neto", "ganadoras", "usd"), ("resto_neto", "resto", "usd"), ("creadores_neto", "creadores", "usd"),
        ("libro_compras", "libro compras", "x"), ("libro_ventas", "libro ventas", "x"),
        ("oi_cambio", "OI Binance", "pct"), ("binance_agresivo_neto", "Binance agresivo", "usd"),
        ("cuentas_lc_cambio", "L/C cuentas", "n"))


def report(eps: list[Episodio]) -> list[str]:
    if not eps:
        return ["Sin episodios en los datos (hacen falta los CSV por minuto de la escucha)."]
    lines = [f"Qué pasó en los {BEFORE} min ANTES de cada episodio (BTC). libro ×: liquidez de los creadores "
             f"frente a la hora previa (×0,2 = la quitaron)", ""]
    for e in eps:
        a = e.antes
        lines.append(f"{e.inicio:%a %d %H:%M} {e.tipo:18} {e.precio:>8,.0f} {e.cambio * 100:+5.1f}% | "
                     + " · ".join(f"{label} {_m(a.get(k), kind)}" for k, label, kind in COLS))
    lines += ["", "Resumen por tipo (media; entre paréntesis, en cuántos casos fue positivo):"]
    for tipo in ORDER:
        es = [e for e in eps if e.tipo == tipo]
        if not es:
            continue
        parts = []
        for k, label, kind in COLS:
            vals = [e.antes.get(k) for e in es if e.antes.get(k) is not None]
            if not vals:
                continue
            pos = sum(v > (1 if kind == "x" else 0) for v in vals)
            parts.append(f"{label} {_m(fmean(vals), kind)} ({pos}/{len(vals)})")
        lines.append(f"  {tipo} — {len(es)} caso(s): " + (" · ".join(parts) if parts else "sin datos previos"))
    lines.append("Pocos casos: sirve para ir viendo patrones; las conclusiones, con semanas de datos.")
    return lines


def default_files(root: Path = Path("data")) -> tuple[list[Path], list[Path]]:
    """Los CSV de la escucha en `data/` y las copias de `data/escucha_pc/*/`."""
    flows = sorted(root.glob("hft_flujo*.csv")) + sorted(root.glob("escucha_pc/*/hft_flujo*.csv"))
    bins = sorted(root.glob("escucha_pc/*/binance_minuto.csv")) + sorted(root.glob("binance_minuto.csv"))
    return flows, bins
