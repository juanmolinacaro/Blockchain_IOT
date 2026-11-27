"""Mapa de liquidez separado por apalancamiento: 100x, 50x y 25x por separado (26 nov 2026).

Idea de Juan (TradeDifferent explica sus pools así): "los de 100x son los que más se liquidan; los de 25x y 5x
muchas veces no los toca en años; puede ser por eso que los pools no dan los resultados". Se repite el estudio de
`mapa_liquidez.py` con un modelo de UN solo apalancamiento cada vez (mismos datos, mismo método: 2 zonas por lado,
±8 %, vida media 24 h, cada 4 h, BTC y ETH 1H ~208 días) y se compara cada pool con un nivel cualquiera a la MISMA
distancia: así la diferencia no viene de que los de 100x estén más cerca.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mapa_liquidez import first_touch, reaction                         # noqa: E402
from copytrading.method.liqmodel import LiquidationModel               # noqa: E402
from copytrading.sources.hyperliquid import HyperliquidSource          # noqa: E402

LOOK, STEP, H, RNG = 192, 4, 24, 0.08


def zones(c, lev, top=2):
    m = LiquidationModel(leverage_weights={lev: 1.0}, decay_per_bar=0.5 ** (1 / 24))
    for k in c:
        m.update(k)
    px, out = c[-1].c, []
    for side, book in (("long", m.longs), ("short", m.shorts)):
        lv = {b: v for b, v in book.items() if abs(m.price_of(b) / px - 1) <= RNG}
        zs, used = [], set()
        for b in sorted(lv, key=lambda k: -lv[k]):
            if b in used:
                continue
            used.update(range(b - 2, b + 3))
            zs.append((side, m.price_of(b), sum(lv.get(k, 0) for k in range(b - 2, b + 3))))
            if len(zs) == top:
                break
        out += zs
    return out


def main() -> None:
    src, now = HyperliquidSource(), int(time.time() * 1000)
    data = {c: [k for k in src.candles(c, "1h", now - 220 * 86_400_000, now) if k.t + 3_600_000 <= now] for c in ("BTC", "ETH")}
    base_cache = {}

    def base(coin, dist, side):
        key = (coin, side, round(dist * 400) / 400)
        if key not in base_cache:
            c, n, h, reac = data[coin], 0, 0, {}
            for i in range(LOOK, len(c) - H, 3):
                lvl = c[i].c * (1 + key[2]) if side == "short" else c[i].c * (1 - key[2])
                n += 1
                j = first_touch(c, i, lvl, side)
                if j:
                    h += 1
                    r = reaction(c, j, lvl, side)
                    reac[r] = reac.get(r, 0) + 1
            base_cache[key] = (h / n if n else 0, reac)
        return base_cache[key]

    for lev in (100, 50, 25):
        rows = []
        for coin, c in data.items():
            for i in range(LOOK, len(c) - H, STEP):
                for side, lvl, usd in zones(c[i - LOOK + 1:i + 1], lev):
                    d = abs(lvl / c[i].c - 1)
                    j = first_touch(c, i, lvl, side)
                    b, _ = base(coin, d, side)
                    rows.append((d, j is not None, b, reaction(c, j, lvl, side) if j else None, coin, side))
        n = len(rows)
        t = [r for r in rows if r[1]]
        reb = sum(r[3] == "rebota" for r in t) / max(len(t), 1)
        sig = sum(r[3] == "sigue" for r in t) / max(len(t), 1)
        br = {}
        for r in t:
            for k, v in base(r[4], r[0], r[5])[1].items():
                br[k] = br.get(k, 0) + v
        tb = sum(br.values()) or 1
        dmed = sorted(r[0] for r in rows)[n // 2]
        print(f"{lev:>3}x: {n:5} pools · distancia mediana {dmed:.1%} · tocados en 24 h {len(t) / n:.0%} "
              f"(nivel cualquiera a la misma distancia {sum(r[2] for r in rows) / n:.0%}) · al tocar: rebota {reb:.0%} / "
              f"sigue {sig:.0%} (cualquiera {br.get('rebota', 0) / tb:.0%} / {br.get('sigue', 0) / tb:.0%})")


if __name__ == "__main__":
    main()
