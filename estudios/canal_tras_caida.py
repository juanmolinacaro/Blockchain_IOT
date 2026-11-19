"""Canal después de una caída: ¿alcista (bandera bajista) o bajista? ¿Por dónde rompe? (19 nov 2026)

Lectura de Juan: "en todas las caídas de estos últimos meses el precio hizo canales alcistas y reventaba hacia
abajo; esta vez veo un canal bajista". BTC 4H de Hyperliquid desde 2020. Se busca, cada 6 velas, una ventana de
30 velas de 4H (5 días) que empieza al menos 8 % debajo del máximo de los 10 días anteriores (canal tras caída).
El canal es la regresión de los cierres ±2 desviaciones; alcista si sube > 0,02 % por vela, bajista si baja más
de eso. Se mira qué línea rompe primero un cierre en las 30 velas siguientes y cuánto se mueve el precio 30 velas
después de la ruptura. Ventanas que se solapan con una anterior ya contada se saltan.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from statistics import fmean, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copytrading.sources.hyperliquid import HyperliquidSource   # noqa: E402

N, LOOK, DROP, SLOPE, AFTER = 30, 60, 0.08, 0.0002, 30


def candles() -> list:
    src, now, out, t = HyperliquidSource(), int(time.time() * 1000), {}, 1_577_836_800_000
    while t < now:
        part = src.candles("BTC", "4h", t, now)
        if not part:
            break
        for c in part:
            out[c.t] = c
        nt = part[-1].t + 1
        if nt <= t:
            break
        t = nt
    return [out[k] for k in sorted(out)]


def fit(c):
    xs = list(range(len(c)))
    ys = [k.c for k in c]
    mx, my = fmean(xs), fmean(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    a = my - b * mx
    return a, b, pstdev([y - (a + b * x) for x, y in zip(xs, ys)])


def main() -> None:
    c = candles()
    rows, i = [], LOOK + N
    while i < len(c) - AFTER - 1:
        start = i - N
        peak = max(k.h for k in c[start - LOOK:start])
        if c[start].c > peak * (1 - DROP):
            i += 6
            continue
        a, b, sd = fit(c[start:i])
        slope = b / c[start].c
        kind = "alcista" if slope > SLOPE else "bajista" if slope < -SLOPE else "plano"
        brk, j = None, None
        for j in range(i, i + AFTER):
            mid = a + b * (j - start)
            if c[j].c > mid + 2 * sd:
                brk = "arriba"
                break
            if c[j].c < mid - 2 * sd:
                brk = "abajo"
                break
        move = c[j + AFTER].c / c[j].c - 1 if brk and j + AFTER < len(c) else None
        rows.append((c[i].t, kind, brk or "no rompe", move, c[i].c))
        i += N                                   # sin solapar
    import datetime as dt
    for t, kind, brk, mv, px in rows:
        print(f"{dt.datetime.utcfromtimestamp(t / 1000):%Y-%m-%d} canal {kind:7} → rompe {brk:8} "
              f"{'' if mv is None else f'{mv:+.1%} en 5 días'}  ({px:,.0f})")
    print()
    for kind in ("alcista", "bajista", "plano"):
        g = [r for r in rows if r[1] == kind]
        if not g:
            continue
        up = [r for r in g if r[2] == "arriba"]
        dn = [r for r in g if r[2] == "abajo"]
        avg = lambda xs: fmean(xs) if xs else 0.0
        print(f"Canal {kind} tras caída: {len(g)} casos · rompe arriba {len(up)} (después {avg([r[3] for r in up if r[3] is not None]):+.1%}) · "
              f"rompe abajo {len(dn)} (después {avg([r[3] for r in dn if r[3] is not None]):+.1%}) · no rompe {len(g) - len(up) - len(dn)}")


if __name__ == "__main__":
    main()
