"""¿Funciona el mapa de liquidez del radar? (26 nov 2026)

Pedido de Juan: medir formalmente los pools 100x (los niveles lila del radar). Se reproduce el mapa tal como lo
calcula la escucha (`short_term_zones`: posiciones 25–100x de los últimos 8 días, 2 zonas por lado a ±4 %) cada 4 h
sobre BTC y ETH 1H de Hyperliquid (~208 días), y se mide:

1. ¿Se tocan? Porcentaje de pools tocados en 24 h, frente a un nivel cualquiera a la MISMA distancia (línea base:
   la probabilidad de que el precio recorra esa distancia en 24 h hacia ese lado, sacada de todas las horas).
2. ¿Va primero al lado más cargado? (imán)
3. ¿Qué hace al tocarlo? En las 4 h siguientes: rebota (vuelve 0,5 % hacia atrás antes de pasar 0,5 % más allá)
   o sigue (pasa 0,5 % más allá primero). Por separado a favor y en contra de la tendencia.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copytrading.method.monitor import trend_state                    # noqa: E402
from copytrading.method.shortliq import short_term_zones              # noqa: E402
from copytrading.sources.hyperliquid import HyperliquidSource         # noqa: E402

STEP, LOOK, HORIZON, REACT, MOVE = 4, 192, 24, 4, 0.005


def first_touch(c, i, level, side):
    for j in range(i + 1, min(len(c), i + 1 + HORIZON)):
        if (c[j].h >= level) if side == "short" else (c[j].l <= level):
            return j
    return None


def reaction(c, j, level, side):
    """Tras tocar en la vela j: 'rebota' si vuelve MOVE hacia atrás antes de pasar MOVE más allá; 'sigue' al revés."""
    back = level * (1 - MOVE) if side == "short" else level * (1 + MOVE)
    beyond = level * (1 + MOVE) if side == "short" else level * (1 - MOVE)
    for k in range(j, min(len(c), j + 1 + REACT)):
        hit_b = (c[k].h >= beyond) if side == "short" else (c[k].l <= beyond)
        hit_r = (c[k].l <= back) if side == "short" else (c[k].h >= back)
        if k == j:
            hit_r = (c[k].c <= back) if side == "short" else (c[k].c >= back)   # en la vela del toque, solo el cierre
        if hit_b and hit_r:
            return "dudoso"
        if hit_b:
            return "sigue"
        if hit_r:
            return "rebota"
    return "nada"


BASE_REAC: dict = {}


def baseline(c, dist, side):
    """Probabilidad de que el precio recorra `dist` hacia ese lado en 24 h (todas las horas) y, si llega, qué hace
    (se acumula en BASE_REAC para comparar la reacción en un pool con la de un nivel cualquiera)."""
    n = hit = 0
    for i in range(LOOK, len(c) - HORIZON, 2):
        lvl = c[i].c * (1 + dist) if side == "short" else c[i].c * (1 - dist)
        n += 1
        j = first_touch(c, i, lvl, side)
        if j is not None:
            hit += 1
            r = reaction(c, j, lvl, side)
            BASE_REAC[r] = BASE_REAC.get(r, 0) + 1
    return hit / n if n else 0.0


def main() -> None:
    src, now = HyperliquidSource(), int(time.time() * 1000)
    rows, snaps = [], []
    for coin in ("BTC", "ETH"):
        c = [k for k in src.candles(coin, "1h", now - 220 * 86_400_000, now) if k.t + 3_600_000 <= now]
        c4 = src.candles(coin, "4h", now - 1000 * 86_400_000, now)
        bands = {}
        for i in range(LOOK, len(c) - HORIZON, STEP):
            L, S = short_term_zones(c[i - LOOK + 1:i + 1])
            px = c[i].c
            tr = trend_state([k for k in c4 if k.t + 4 * 3_600_000 <= c[i].t + 3_600_000])[0]
            tl = [first_touch(c, i, z.center, "long") for z in L]
            ts = [first_touch(c, i, z.center, "short") for z in S]
            up, down = sum(z.usd for z in S), sum(z.usd for z in L)
            cand = [(j, "short") for j in ts if j] + [(j, "long") for j in tl if j]
            if cand and L and S:
                snaps.append({"primero": min(cand)[1], "mayor": "short" if up >= down else "long",
                              "fuerte": max(up, down) >= 1.5 * max(min(up, down), 1)})
            for side, zs, touch in (("long", L, tl), ("short", S, ts)):
                for z, j in zip(zs, touch):
                    dist = abs(z.center / px - 1)
                    band = round(dist * 100 * 2) / 2                       # 0,5 %
                    bands.setdefault((side, band), None)
                    rows.append({"coin": coin, "side": side, "dist": dist, "band": band, "tocado": j is not None,
                                 "horas": (j - i) if j else None,
                                 "reac": reaction(c, j, z.center, side) if j else None,
                                 "favor": (tr == "BAJISTA") == (side == "short"), "usd": z.usd})
        base = {k: baseline(c, max(k[1], 0.25) / 100, k[0]) for k in bands}
        for r in rows:
            if r["coin"] == coin:
                r["base"] = base[(r["side"], r["band"])]
    n = len(rows)
    t = [r for r in rows if r["tocado"]]
    print(f"Pools medidos: {n} (BTC y ETH, cada 4 h) · tocados en 24 h: {len(t)} ({len(t) / n:.0%}) · "
          f"línea base a la misma distancia: {sum(r['base'] for r in rows) / n:.0%}")
    print("\nPor distancia al precio:")
    for lo, hi in ((0, 0.01), (0.01, 0.02), (0.02, 0.03), (0.03, 0.05)):
        g = [r for r in rows if lo <= r["dist"] < hi]
        if g:
            print(f"  {lo * 100:.0f}–{hi * 100:.0f} %: {len(g):4} pools · tocados {sum(r['tocado'] for r in g) / len(g):.0%} · "
                  f"base {sum(r['base'] for r in g) / len(g):.0%} · horas hasta tocar (mediana) "
                  f"{sorted(r['horas'] for r in g if r['horas'])[len([r for r in g if r['horas']]) // 2] if any(r['horas'] for r in g) else '—'}")
    print("\nImán (¿toca primero el lado con más liquidez?):")
    for lab, cond in (("todos los momentos", lambda x: True), ("un lado 1,5× más cargado", lambda x: x["fuerte"])):
        g = [x for x in snaps if cond(x)]
        ok = sum(x["primero"] == x["mayor"] for x in g)
        if g:
            print(f"  {lab}: el primer pool tocado fue el del lado más cargado en {ok}/{len(g)} ({ok / len(g):.0%})")
    print("\nQué hace al tocarlo (4 h siguientes, ±0,5 %):")
    for lab, cond in (("todos", lambda r: True), ("a favor de la tendencia (cortos arriba en bajista…)", lambda r: r["favor"]),
                      ("en contra de la tendencia", lambda r: not r["favor"])):
        g = [r for r in t if cond(r)]
        if g:
            cnt = {k: sum(r["reac"] == k for r in g) for k in ("rebota", "sigue", "nada", "dudoso")}
            print(f"  {lab}: {len(g)} toques · rebota {cnt['rebota'] / len(g):.0%} · sigue {cnt['sigue'] / len(g):.0%} · "
                  f"nada {cnt['nada'] / len(g):.0%} · dudoso {cnt['dudoso'] / len(g):.0%}")
    tb = sum(BASE_REAC.values()) or 1
    print(f"  línea base (nivel cualquiera a la misma distancia): rebota {BASE_REAC.get('rebota', 0) / tb:.0%} · "
          f"sigue {BASE_REAC.get('sigue', 0) / tb:.0%}")


if __name__ == "__main__":
    main()
