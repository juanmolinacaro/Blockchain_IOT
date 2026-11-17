"""Tipos de ruptura, medidos por separado (idea de Juan, 10 nov 2026: "hay varias rupturas: de canal,
de acumulación, etc.").

Cada detector mira solo velas CERRADAS y devuelve rupturas con su entrada (cierre de la vela que rompe)
y su stop (al otro lado de la estructura). Después `evaluate` mide el resultado en R:

* **compresión**: 12 velas con el rango entre el 20 % más estrecho del historial; rompe al cerrar fuera;
* **acumulación / rango**: 36 velas con rango estrecho (30 % más estrecho) y al menos 2 toques arriba y 2
  abajo (a ±0,15 % del borde); rompe al cerrar fuera; stop en el borde contrario;
* **canal**: canal de regresión de 48 velas (±2 desviaciones); rompe la línea contraria a su pendiente
  (canal alcista que pierde la línea de abajo = bandera bajista, como el 9–10 nov); stop sobre el
  extremo de las últimas 6 velas;
* **triángulo**: dos máximos que bajan y dos mínimos que suben (pivotes de 3 velas, últimas 60);
  rompe al cerrar fuera de las líneas; stop en el último pivote contrario;
* **línea de tendencia**: soporte por dos mínimos que suben (o resistencia por dos máximos que bajan);
  rompe al cerrar al otro lado; stop sobre el extremo de las últimas 6 velas.

A favor o en contra de la tendencia se decide con la pendiente de la EMA 50 diaria (regla de Juan).
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean, pstdev

from ..models import Candle
from .emas import ema_series

PAD = 0.001


@dataclass
class Ruptura:
    tipo: str
    i: int
    lado: str          # short | long
    entrada: float
    stop: float


def _ranges(c: list[Candle], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    for i in range(n, len(c)):
        w = c[i - n:i]
        out[i] = max(k.h for k in w) / min(k.l for k in w) - 1
    return out


def _threshold(vals: list[float | None], pct: float) -> float:
    v = sorted(x for x in vals if x is not None)
    return v[int(len(v) * pct)] if v else 0.0


def compresion(c: list[Candle], n: int = 12, pct: float = 0.2) -> list[Ruptura]:
    rng = _ranges(c, n)
    thr = _threshold(rng, pct)
    out, i = [], n
    while i < len(c):
        if rng[i] is not None and rng[i] <= thr:
            box = c[i - n:i]
            hi, lo = max(k.h for k in box), min(k.l for k in box)
            if c[i].c < lo:
                out.append(Ruptura("compresión", i, "short", c[i].c, hi * (1 + PAD)))
                i += n
                continue
            if c[i].c > hi:
                out.append(Ruptura("compresión", i, "long", c[i].c, lo * (1 - PAD)))
                i += n
                continue
        i += 1
    return out


def acumulacion(c: list[Candle], n: int = 36, pct: float = 0.3, touch: float = 0.0015) -> list[Ruptura]:
    rng = _ranges(c, n)
    thr = _threshold(rng, pct)
    out, i = [], n
    while i < len(c):
        if rng[i] is not None and rng[i] <= thr:
            box = c[i - n:i]
            hi, lo = max(k.h for k in box), min(k.l for k in box)
            tops = sum(1 for k in box if k.h >= hi * (1 - touch))
            bots = sum(1 for k in box if k.l <= lo * (1 + touch))
            if tops >= 2 and bots >= 2:
                if c[i].c < lo:
                    out.append(Ruptura("acumulación", i, "short", c[i].c, hi * (1 + PAD)))
                    i += n
                    continue
                if c[i].c > hi:
                    out.append(Ruptura("acumulación", i, "long", c[i].c, lo * (1 - PAD)))
                    i += n
                    continue
        i += 1
    return out


def canal(c: list[Candle], n: int = 48, k_sd: float = 2.0, cool: int = 12) -> list[Ruptura]:
    out, i = [], n
    xs = list(range(n))
    mx = fmean(xs)
    sxx = sum((x - mx) ** 2 for x in xs)
    while i < len(c):
        ys = [k.c for k in c[i - n:i]]
        my = fmean(ys)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        a = my - b * mx
        sd = pstdev([y - (a + b * x) for x, y in zip(xs, ys)]) or 1e-9
        mid = a + b * n                                   # la línea proyectada a la vela actual
        slope = b / my
        last6 = c[i - 6:i]
        if slope > 0.0002 and c[i].c < mid - k_sd * sd:    # canal alcista que pierde la línea de abajo
            out.append(Ruptura("canal", i, "short", c[i].c, max(k.h for k in last6 + [c[i]]) * (1 + PAD)))
            i += cool
            continue
        if slope < -0.0002 and c[i].c > mid + k_sd * sd:   # canal bajista que rompe la línea de arriba
            out.append(Ruptura("canal", i, "long", c[i].c, min(k.l for k in last6 + [c[i]]) * (1 - PAD)))
            i += cool
            continue
        i += 1
    return out


def _pivots(c: list[Candle], k: int, start: int, end: int) -> tuple[list[int], list[int]]:
    highs, lows = [], []
    for j in range(max(start, k), end - k):
        w = c[j - k:j + k + 1]
        if c[j].h == max(x.h for x in w):
            highs.append(j)
        if c[j].l == min(x.l for x in w):
            lows.append(j)
    return highs, lows


def _line(i1: int, p1: float, i2: int, p2: float, at: int) -> float:
    return p1 + (p2 - p1) * (at - i1) / (i2 - i1)


def triangulo(c: list[Candle], look: int = 60, k: int = 3, cool: int = 12) -> list[Ruptura]:
    out, i = [], look
    while i < len(c):
        hs, ls = _pivots(c, k, i - look, i)
        if len(hs) >= 2 and len(ls) >= 2:
            h1, h2, l1, l2 = hs[-2], hs[-1], ls[-2], ls[-1]
            if c[h2].h < c[h1].h and c[l2].l > c[l1].l:
                top = _line(h1, c[h1].h, h2, c[h2].h, i)
                bot = _line(l1, c[l1].l, l2, c[l2].l, i)
                if top > bot:
                    if c[i].c < bot:
                        out.append(Ruptura("triángulo", i, "short", c[i].c, c[h2].h * (1 + PAD)))
                        i += cool
                        continue
                    if c[i].c > top:
                        out.append(Ruptura("triángulo", i, "long", c[i].c, c[l2].l * (1 - PAD)))
                        i += cool
                        continue
        i += 1
    return out


def linea_tendencia(c: list[Candle], look: int = 60, k: int = 3, cool: int = 12) -> list[Ruptura]:
    out, i = [], look
    while i < len(c):
        hs, ls = _pivots(c, k, i - look, i)
        last6 = c[i - 6:i]
        done = False
        if len(ls) >= 2 and c[ls[-1]].l > c[ls[-2]].l:                 # soporte que sube
            sup = _line(ls[-2], c[ls[-2]].l, ls[-1], c[ls[-1]].l, i)
            if c[i].c < sup and c[i - 1].c >= _line(ls[-2], c[ls[-2]].l, ls[-1], c[ls[-1]].l, i - 1):
                out.append(Ruptura("línea de tendencia", i, "short", c[i].c,
                                   max(x.h for x in last6 + [c[i]]) * (1 + PAD)))
                done = True
        if not done and len(hs) >= 2 and c[hs[-1]].h < c[hs[-2]].h:      # resistencia que baja
            res = _line(hs[-2], c[hs[-2]].h, hs[-1], c[hs[-1]].h, i)
            if c[i].c > res and c[i - 1].c <= _line(hs[-2], c[hs[-2]].h, hs[-1], c[hs[-1]].h, i - 1):
                out.append(Ruptura("línea de tendencia", i, "long", c[i].c,
                                   min(x.l for x in last6 + [c[i]]) * (1 - PAD)))
                done = True
        i += cool if done else 1
    return out


DETECTORES = (compresion, acumulacion, canal, triangulo, linea_tendencia)


def trend_at(c: list[Candle], e50: list, i: int, bars_6d: int) -> str:
    back = i - bars_6d
    if back < 0 or not e50[i] or not e50[back]:
        return ""
    return "ALCISTA" if e50[i] > e50[back] else "BAJISTA"


def outcome(c: list[Candle], r: Ruptura, horizon: int, fee: float = 0.0009) -> dict:
    """R a 1R, 1,5R, 2R (todo o nada) y con la regla de Juan (mitad en 1R, stop a la entrada, resto a 2R),
    menos la comisión en R. Si en una vela se tocan stop y objetivo, cuenta el stop."""
    short = r.lado == "short"
    risk = abs(r.stop - r.entrada)
    if risk <= 0:
        return {}
    fee_r = fee * r.entrada / risk
    res = {"riesgo_pct": risk / r.entrada}
    for tgt in (1.0, 1.5, 2.0):
        tp = r.entrada - tgt * risk if short else r.entrada + tgt * risk
        o = 0.0
        for k in c[r.i + 1:r.i + 1 + horizon]:
            if (k.h >= r.stop) if short else (k.l <= r.stop):
                o = -1.0
                break
            if (k.l <= tp) if short else (k.h >= tp):
                o = tgt
                break
        res[tgt] = o - fee_r
    o, half, stop = 0.0, False, r.stop
    t1 = r.entrada - risk if short else r.entrada + risk
    t2 = r.entrada - 2 * risk if short else r.entrada + 2 * risk
    for k in c[r.i + 1:r.i + 1 + horizon]:
        if (k.h >= stop) if short else (k.l <= stop):
            o = o if half else -1.0
            break
        if not half and ((k.l <= t1) if short else (k.h >= t1)):
            half, o, stop = True, 0.5, r.entrada
        if half and ((k.l <= t2) if short else (k.h >= t2)):
            o = 1.5
            break
    res["juan"] = o - fee_r
    return res


def study(candles: dict[str, list[Candle]], bars_per_day: int, horizon: int) -> dict:
    """{(tipo, 'a favor'|'en contra'): [resultados]} para varias monedas."""
    out: dict = {}
    for coin, c in candles.items():
        e50 = ema_series(c, "1d", 50)
        for det in DETECTORES:
            for r in det(c):
                tr = trend_at(c, e50, r.i, 6 * bars_per_day)
                if not tr:
                    continue
                fav = (tr == "BAJISTA") == (r.lado == "short")
                res = outcome(c, r, horizon)
                if res:
                    out.setdefault((r.tipo, "a favor" if fav else "en contra"), []).append(res)
    return out


def report(res: dict, title: str) -> list[str]:
    lines = [title, f"{'ruptura':20} {'tendencia':9} {'casos':>5} {'TP 1R':>7} {'acierto':>7} {'TP 1,5R':>8} "
                    f"{'TP 2R':>7} {'Juan':>7} {'riesgo':>7}"]
    tipos = ["compresión", "acumulación", "canal", "triángulo", "línea de tendencia"]
    for t in tipos:
        for side in ("a favor", "en contra"):
            rs = res.get((t, side), [])
            if not rs:
                continue
            m = lambda k: fmean(x[k] for x in rs)
            win = sum(x[1.0] > 0 for x in rs) / len(rs)
            lines.append(f"{t:20} {side:9} {len(rs):5} {m(1.0):+7.2f} {win:7.0%} {m(1.5):+8.2f} {m(2.0):+7.2f} "
                         f"{m('juan'):+7.2f} {fmean(x['riesgo_pct'] for x in rs) * 100:6.2f}%")
    lines.append("R por operación, ya descontada la comisión (0,09 % ida y vuelta). Juan = mitad en 1R, stop a la "
                 "entrada, resto a 2R.")
    return lines
