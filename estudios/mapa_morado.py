"""¿Funcionan las franjas moradas del radar ("liquidez largos / cortos")? (26 nov 2026)

Mismo método que `mapa_liquidez.py` (lila, 100x), para la capa morada: el nivel de largos más cargado debajo y el
de cortos más cargado encima, a ±8 %, del modelo con todos los apalancamientos (vida media 14 días) sobre velas de 4H
(`compute_liquidity` con la configuración del radar). BTC y ETH de Hyperliquid, ~830 días, cada vela de 4H.

1. ¿Se toca en 3 días? frente a un nivel cualquiera a la misma distancia y del mismo lado.
2. Imán: ¿toca primero el lado con más liquidez total?
3. Al tocarlo: en las 2 velas de 4H siguientes, ¿vuelve 1 % atrás (rebota) o pasa 1 % más allá (sigue)?
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copytrading.method.backtest import compute_liquidity               # noqa: E402
from copytrading.method.monitor import VARIANTS                         # noqa: E402
from copytrading.sources.hyperliquid import HyperliquidSource           # noqa: E402

H, R, MOVE, WARM = 18, 2, 0.01, 200


def touch(c, i, lvl, side):
    for j in range(i + 1, min(len(c), i + 1 + H)):
        if (c[j].h >= lvl) if side == "short" else (c[j].l <= lvl):
            return j
    return None


def react(c, j, lvl, side):
    back = lvl * (1 - MOVE) if side == "short" else lvl * (1 + MOVE)
    beyond = lvl * (1 + MOVE) if side == "short" else lvl * (1 - MOVE)
    for k in range(j, min(len(c), j + 1 + R)):
        b = (c[k].h >= beyond) if side == "short" else (c[k].l <= beyond)
        r = ((c[k].c <= back) if side == "short" else (c[k].c >= back)) if k == j else \
            ((c[k].l <= back) if side == "short" else (c[k].h >= back))
        if b and r:
            return "dudoso"
        if b:
            return "sigue"
        if r:
            return "rebota"
    return "nada"


def main() -> None:
    src, now = HyperliquidSource(), int(time.time() * 1000)
    rows, snaps, base_r = [], [], {}
    for coin in ("BTC", "ETH"):
        c = [k for k in src.candles(coin, "4h", now - 900 * 86_400_000, now) if k.t + 4 * 3_600_000 <= now]
        liq = compute_liquidity(c, VARIANTS["sistema-A"])
        base_cache = {}

        def base(dist, side):
            key = (side, round(dist * 200) / 200)
            if key not in base_cache:
                n = hit = 0
                d = max(key[1], 0.0025)
                for i in range(WARM, len(c) - H, 3):
                    lvl = c[i].c * (1 + d) if side == "short" else c[i].c * (1 - d)
                    n += 1
                    j = touch(c, i, lvl, side)
                    if j:
                        hit += 1
                        x = react(c, j, lvl, side)
                        base_r[x] = base_r.get(x, 0) + 1
                base_cache[key] = hit / n
            return base_cache[key]

        for i in range(WARM, len(c) - H):
            s, px = liq[i], c[i].c
            js = {}
            for side, lvl in (("long", s.best_long_px), ("short", s.best_short_px)):
                if not lvl:
                    continue
                j = touch(c, i, lvl, side)
                js[side] = j
                rows.append({"dist": abs(lvl / px - 1), "tocado": j is not None, "base": base(abs(lvl / px - 1), side),
                             "reac": react(c, j, lvl, side) if j else None})
            if js.get("long") or js.get("short"):
                first = min((j, sd) for sd, j in js.items() if j)[1]
                bigger = "long" if s.long_below >= s.short_above else "short"
                strong = max(s.long_below, s.short_above) >= 1.5 * max(min(s.long_below, s.short_above), 1e-9)
                snaps.append((first == bigger, strong))
    n = len(rows)
    t = [r for r in rows if r["tocado"]]
    print(f"Franjas moradas medidas: {n} (BTC y ETH, cada 4 h, ~830 días) · tocadas en 3 días {len(t) / n:.0%} · "
          f"línea base {sum(r['base'] for r in rows) / n:.0%}")
    for lo, hi in ((0, 0.02), (0.02, 0.04), (0.04, 0.06), (0.06, 0.09)):
        g = [r for r in rows if lo <= r["dist"] < hi]
        if g:
            print(f"  {lo * 100:.0f}–{hi * 100:.0f} %: {len(g):5} · tocadas {sum(r['tocado'] for r in g) / len(g):.0%} · "
                  f"base {sum(r['base'] for r in g) / len(g):.0%}")
    for lab, cond in (("todos", lambda x: True), ("un lado 1,5× más cargado", lambda x: x[1])):
        g = [x for x in snaps if cond(x)]
        print(f"Imán ({lab}): primero el lado más cargado en {sum(x[0] for x in g)}/{len(g)} ({sum(x[0] for x in g) / len(g):.0%})")
    cnt = {k: sum(r["reac"] == k for r in t) for k in ("rebota", "sigue", "nada", "dudoso")}
    tb = sum(base_r.values()) or 1
    print(f"Al tocarla (8 h, ±1 %): rebota {cnt['rebota'] / len(t):.0%} · sigue {cnt['sigue'] / len(t):.0%} · "
          f"nada {cnt['nada'] / len(t):.0%} | nivel cualquiera: rebota {base_r.get('rebota', 0) / tb:.0%} · "
          f"sigue {base_r.get('sigue', 0) / tb:.0%}")


if __name__ == "__main__":
    main()
