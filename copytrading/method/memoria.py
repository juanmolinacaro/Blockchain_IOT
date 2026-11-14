"""Memoria de patrones: ¿a qué momentos del pasado se parece el mercado de ahora y qué pasó después?

Idea de Juan (5 nov 2026): el mercado repite comportamientos humanos; lo que nos falla es la memoria.
Cada vela de 4H se describe con unos pocos rasgos medibles (tendencia, posición frente a las EMA
diarias, canal, imán de liquidez, movimiento y volumen recientes, ruptura o trampa reciente). Para el
momento actual se buscan las situaciones más parecidas del historial (BTC + ETH + SOL, ~2,3 años) y
se resume qué hizo el precio en las 24 h y 72 h siguientes.

Además hay un archivo de **casos anotados** (`data/casos.json`): momentos que Juan y Claude marcaron
a mano con lo que pasó; si el mercado actual se parece a uno, se avisa con su descripción.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..models import Candle

CASES = Path("data/casos.json")
COT = timezone(timedelta(hours=-5))
BAR_H = 4
FEATURES = ("tendencia", "vs_ema50", "vs_ema200", "canal", "iman", "mov_24h", "mov_72h",
            "rango_24h", "volumen", "ruptura")
WEIGHTS = {"tendencia": 1.5, "vs_ema50": 1.0, "vs_ema200": 1.0, "canal": 1.0, "iman": 1.2,
           "mov_24h": 1.0, "mov_72h": 1.0, "rango_24h": 0.6, "volumen": 0.6, "ruptura": 1.2}


@dataclass
class State:
    coin: str
    t: int
    price: float
    f: dict                        # rasgos
    fwd: dict = field(default_factory=dict)   # resultado: {"24h": %, "72h": %} (si ya pasó)


def features(coin: str, candles: list[Candle]) -> list[State | None]:
    """Rasgos de cada vela de 4H cerrada (None mientras no hay historia suficiente)."""
    from .backtest import compute_liquidity
    from .channels import regression_channel
    from .emas import ema_series
    from .monitor import VARIANTS

    e50, e200 = ema_series(candles, "1d", 50), ema_series(candles, "1d", 200)
    liq = compute_liquidity(candles, VARIANTS["sistema-A"])
    out: list[State | None] = []
    vols = [c.v * c.c for c in candles]
    for i, c in enumerate(candles):
        if i < 200 or not e50[i] or not e200[i] or not e50[i - 36]:
            out.append(None)
            continue
        ch = regression_channel(candles, i, 60)
        if ch is None:
            out.append(None)
            continue
        lo, up = ch.lower(i), ch.upper(i)
        canal = (c.c - lo) / (up - lo) if up > lo else 0.5
        s = liq[i]
        iman = math.log((s.long_below + 1) / (s.short_above + 1))      # >0: más liquidez abajo
        win = candles[i - 5:i + 1]
        rng = (max(x.h for x in win) - min(x.l for x in win)) / c.c
        vol = statistics.fmean(vols[i - 5:i + 1]) / (statistics.fmean(vols[i - 180:i - 5]) or 1)
        prev = candles[i - 11:i - 5]                                    # 24 h anteriores a las últimas 24 h
        hi, lo24 = max(x.h for x in prev), min(x.l for x in prev)
        recent = candles[i - 5:i + 1]
        rup = 0.0
        if max(x.h for x in recent) > hi:                               # rompió arriba…
            rup = 1.0 if c.c > hi else -0.5                             # …y sigue fuera, o volvió (trampa alcista)
        if min(x.l for x in recent) < lo24:
            rup = -1.0 if c.c < lo24 else 0.5                           # trampa bajista = +0,5
        out.append(State(coin, c.t, c.c, {
            "tendencia": e50[i] / e50[i - 36] - 1,
            "vs_ema50": c.c / e50[i] - 1,
            "vs_ema200": c.c / e200[i] - 1,
            "canal": max(-0.5, min(1.5, canal)),
            "iman": max(-3.0, min(3.0, iman)),
            "mov_24h": c.c / candles[i - 6].c - 1,
            "mov_72h": c.c / candles[i - 18].c - 1,
            "rango_24h": rng,
            "volumen": math.log(max(vol, 1e-6)),
            "ruptura": rup,
        }))
        st = out[-1]
        for name, bars in (("24h", 6), ("72h", 18)):
            if i + bars < len(candles):
                st.fwd[name] = candles[i + bars].c / c.c - 1
    return out


def scales(states: list[State]) -> dict:
    return {k: (statistics.pstdev(s.f[k] for s in states) or 1.0) for k in FEATURES}


def distance(a: dict, b: dict, sc: dict) -> float:
    return math.sqrt(sum(WEIGHTS[k] * ((a[k] - b[k]) / sc[k]) ** 2 for k in FEATURES))


def analogs(query: State, library: list[State], sc: dict, k: int = 10, gap_days: float = 3,
            horizon: str = "72h") -> list[tuple[float, State]]:
    """Las k situaciones más parecidas, separadas entre sí ≥ gap_days y anteriores a la consulta."""
    gap = gap_days * 86_400_000
    cands = sorted(((distance(query.f, s.f, sc), s) for s in library
                    if s.fwd.get(horizon) is not None and s.t < query.t - 3 * 86_400_000),
                   key=lambda x: x[0])
    picked: list[tuple[float, State]] = []
    for d, s in cands:
        if all(abs(s.t - p.t) >= gap or s.coin != p.coin for _, p in picked):
            picked.append((d, s))
            if len(picked) == k:
                break
    return picked


def summarize(picked: list[tuple[float, State]]) -> dict:
    out = {}
    for h in ("24h", "72h"):
        v = [s.fwd[h] for _, s in picked if h in s.fwd]
        if v:
            out[h] = {"n": len(v), "suben": sum(x > 0 for x in v), "mediana": statistics.median(v)}
    return out


def describe(coin: str, picked: list[tuple[float, State]]) -> list[str]:
    sm = summarize(picked)
    if not sm:
        return []
    fmt = lambda x: f"{x * 100:+.1f} %".replace(".", ",")
    lines = []
    for h in ("24h", "72h"):
        if h in sm:
            d = sm[h]
            lines.append(f"Memoria {coin}: en {d['n']} situaciones parecidas, a {h.replace('h', ' h')} subió en "
                         f"{d['suben']} y bajó en {d['n'] - d['suben']} (mediana {fmt(d['mediana'])})")
    best = picked[:3]
    lines.append("Más parecidas: " + "; ".join(
        f"{datetime.fromtimestamp(s.t / 1000, COT):%d %b %Y} {s.coin} ({fmt(s.fwd.get('72h', 0))} en 72 h)"
        for _, s in best))
    return lines


# ----------------------------------------------------------------- casos anotados
def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def case_match(query: State, cases: list[dict], sc: dict, max_dist: float = 2.5) -> list[tuple[float, dict]]:
    """Casos anotados cuyo estado se parece al actual (distancia ≤ max_dist)."""
    out = []
    for c in cases:
        if not c.get("rasgos") or c.get("moneda") not in (query.coin, "*"):
            continue
        if abs(c.get("t", 0) - query.t) < 2 * 86_400_000:       # el propio caso
            continue
        d = distance(query.f, c["rasgos"], sc)
        if d <= max_dist:
            out.append((d, c))
    return sorted(out, key=lambda x: x[0])


# ------------------------------------------------- memoria útil: patrones medidos y casos
# Prueba del 6 nov 2026 (paso a paso, sin mirar el futuro): buscar "el momento más parecido" con todos
# los rasgos a la vez NO predijo la dirección (48-51 % de acierto frente a 49 % de base). Lo que sí
# funciona son patrones concretos medidos uno a uno. La memoria recuerda esos patrones con sus números
# y los casos reales que Juan y Claude anotaron.
PATTERN_STATS = {
    "tendencia_bajista": "Tendencia bajista: a favor (cortos) +0,43R de media; en contra (largos) −0,10R",
    "tendencia_alcista": "Tendencia alcista: a favor (largos) +0,43R de media; en contra (cortos) −0,10R",
    "trampa_alcista": "Ruptura alcista que volvió dentro (trampa): en 4H el precio llega al otro extremo del "
                      "rango el 44 % de las veces en 24 h",
    "trampa_bajista": "Ruptura bajista que volvió dentro (trampa): en 4H el precio llega al otro extremo del "
                      "rango el 44 % de las veces en 24 h",
    "iman_abajo": "Imán ≥ 2x abajo: el precio llegó antes al pool grande 8 de cada 10 veces (4H)",
    "iman_arriba": "Imán ≥ 2x arriba: el precio llegó antes al pool grande 8 de cada 10 veces (4H)",
    "perdio_ema200": "Perdió la EMA 200 diaria con cierre de 4H: soporte roto, se busca venta en el retest",
    "recupero_ema200": "Recuperó la EMA 200 diaria con cierre de 4H",
    "movimiento_fuerte": "Movimiento ≥ 4 % en 24 h: no perseguir; esperar retroceso o barrido",
}


def tags(candles_4h: list[Candle], candles_1h: list[Candle]) -> list[str]:
    """Patrones activos ahora (velas cerradas)."""
    from .backtest import compute_liquidity
    from .emas import ema_series
    from .monitor import VARIANTS, nearest_pools, trend_state
    from .traps import recent_breakouts

    out = []
    tr, _, _ = trend_state(candles_4h)
    if tr in ("ALCISTA", "BAJISTA"):
        out.append("tendencia_" + tr.lower())
    for lb in recent_breakouts(candles_1h, window=24):
        if lb.failed_at:
            out.append("trampa_alcista" if lb.b.up else "trampa_bajista")
    below, above = nearest_pools(candles_4h)
    if below and above:
        if below.size >= 2 * above.size:
            out.append("iman_abajo")
        elif above.size >= 2 * below.size:
            out.append("iman_arriba")
    e200 = ema_series(candles_4h, "1d", 200)
    if e200[-1] and e200[-7]:
        was_above = any(c.c > e for c, e in zip(candles_4h[-7:-1], e200[-7:-1]) if e)
        was_below = any(c.c < e for c, e in zip(candles_4h[-7:-1], e200[-7:-1]) if e)
        if candles_4h[-1].c < e200[-1] and was_above:
            out.append("perdio_ema200")
        if candles_4h[-1].c > e200[-1] and was_below:
            out.append("recupero_ema200")
    if abs(candles_4h[-1].c / candles_4h[-7].c - 1) >= 0.04:
        out.append("movimiento_fuerte")
    return sorted(set(out))


def matching_cases(coin: str, active: list[str], cases: list[dict], min_shared: int = 2,
                   today: str | None = None) -> list[tuple[int, dict]]:
    """Casos anotados que comparten al menos `min_shared` patrones con el momento actual (sin contar los de
    los últimos 3 días: son el mismo episodio que se está viviendo)."""
    today = today or datetime.now(COT).strftime("%Y-%m-%d")
    t0 = datetime.strptime(today, "%Y-%m-%d")
    out = []
    for c in cases:
        if c.get("moneda") not in (coin, "*") or c.get("pendiente"):     # lecturas aún sin resultado: no cuentan
            continue
        if abs((t0 - datetime.strptime(c["fecha"], "%Y-%m-%d")).days) < 3:
            continue
        shared = len(set(c.get("patrones", [])) & set(active))
        if shared >= min_shared:
            out.append((shared, c))
    return sorted(out, key=lambda x: -x[0])


def memory_lines(coin: str, candles_4h: list[Candle], candles_1h: list[Candle],
                 cases: list[dict] | None = None) -> list[str]:
    active = tags(candles_4h, candles_1h)
    lines = [PATTERN_STATS[t] for t in active if t in PATTERN_STATS]
    for shared, c in matching_cases(coin, active, load_cases() if cases is None else cases)[:2]:
        lines.append(f"Se parece a {c['fecha']} ({c['titulo']}): {c['resultado']}")
    return lines


def record_case(coin: str, fecha: str, titulo: str, patrones: list[str], resultado: str,
                path: Path = CASES) -> bool:
    """Añade un caso (si no existe ya ese día y moneda)."""
    cases = load_cases(path)
    day = datetime.strptime(fecha, "%Y-%m-%d")
    if any(c["moneda"] == coin and abs((datetime.strptime(c["fecha"], "%Y-%m-%d") - day).days) <= 2 for c in cases):
        return False                                   # ese movimiento ya está anotado (a mano o solo)
    cases.append({"moneda": coin, "fecha": fecha, "titulo": titulo, "patrones": sorted(set(patrones)),
                  "resultado": resultado})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


def auto_record(coin: str, candles_4h: list[Candle], candles_1h: list[Candle], min_move: float = 0.04) -> str | None:
    """Si en las últimas 24 h hubo un movimiento ≥ 4 %, lo guarda como caso con los patrones que había
    justo antes (así la memoria crece sola con cada movimiento fuerte)."""
    if len(candles_4h) < 250 or len(candles_1h) < 100:
        return None
    move = candles_4h[-1].c / candles_4h[-7].c - 1
    if abs(move) < min_move:
        return None
    before4 = candles_4h[:-6]
    before1 = [c for c in candles_1h if c.t < candles_4h[-6].t]
    active = tags(before4, before1)
    fecha = datetime.fromtimestamp(candles_4h[-6].t / 1000, COT).strftime("%Y-%m-%d")
    lo = min(c.l for c in candles_4h[-6:])
    hi = max(c.h for c in candles_4h[-6:])
    k = lambda x: f"{x:,.0f}".replace(",", ".") if x >= 1000 else f"{x:,.1f}".replace(".", ",")
    pct = f"{abs(move) * 100:.1f}".replace(".", ",")
    res = (f"{'cayó' if move < 0 else 'subió'} {pct} % en 24 h (de {k(before4[-1].c)} a {k(candles_4h[-1].c)}; "
           f"extremo {k(lo if move < 0 else hi)})")
    titulo = f"movimiento fuerte {'bajista' if move < 0 else 'alcista'} (anotado solo)"
    return fecha if record_case(coin, fecha, titulo, active, res) else None
