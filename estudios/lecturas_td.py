"""Lecturas de Juan con TradeDifferent: ¿el precio fue a la zona que marcaba? (26 nov 2026)

Juan manda la captura ANTES del movimiento; se anota en `data/lecturas_td.jsonl`, una línea por captura:

  {"fecha": "2026-11-26 09:15", "moneda": "BTC", "precio": 60950, "fuente": "TradeDifferent",
   "zonas": [{"nivel": 58200, "lado": "largos", "nota": "franja amarilla fuerte"},
             {"nivel": 63400, "lado": "cortos", "nota": ""}],
   "lectura": "lo que dijo Juan, tal cual"}

Para cada zona: si el precio la tocó en 24 h y en 72 h, cuántas horas tardó, qué hizo al tocarla (vuelve 0,5 % atrás
= rebota; pasa 0,5 % más allá = sigue, en 4 h) y, para comparar, la probabilidad de tocar un nivel cualquiera a la
misma distancia (todas las horas de los últimos ~200 días). Con ~30 zonas ya se puede decir si ayuda.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copytrading.sources.hyperliquid import HyperliquidSource   # noqa: E402

COT = timezone(timedelta(hours=-5))
FILE = Path("data/lecturas_td.jsonl")


def main() -> None:
    rows = [json.loads(l) for l in FILE.read_text(encoding="utf-8").splitlines() if l.strip()] if FILE.exists() else []
    if not rows:
        print("Todavía no hay lecturas de TradeDifferent anotadas.")
        return
    src, now = HyperliquidSource(), int(time.time() * 1000)
    cs = {c: [k for k in src.candles(c, "1h", now - 208 * 86_400_000, now) if k.t + 3_600_000 <= now]
          for c in {r["moneda"] for r in rows}}
    tot = hit24 = 0
    base = []
    swing = []
    for r in rows:
        c = cs[r["moneda"]]
        t0 = int(datetime.strptime(r["fecha"], "%Y-%m-%d %H:%M").replace(tzinfo=COT).timestamp() * 1000)
        i = next((k for k, x in enumerate(c) if x.t >= t0), None)
        if i is None:
            continue
        for z in r["zonas"]:
            up = z["lado"] == "cortos"
            lvl = z["nivel"]
            if r.get("plazo") == "swing":                 # niveles de swing (mapas 1D/4H de bajo apalancamiento): 30 días
                j = next((k for k in range(i, min(len(c), i + 720)) if (c[k].h >= lvl if up else c[k].l <= lvl)), None)
                swing.append(j is not None)
                print(f"{r['fecha']} {r['moneda']} {z['lado']:7} {lvl:>9,.0f} ({abs(lvl / r['precio'] - 1):.1%}) [swing]: "
                      f"{'tocada a los ' + str(round((j - i) / 24, 1)) + ' días' if j is not None else 'sin tocar (' + str(round((len(c) - i) / 24, 1)) + ' días)'}")
                continue
            j = next((k for k in range(i, min(len(c), i + 72)) if (c[k].h >= lvl if up else c[k].l <= lvl)), None)
            reac = "—"
            if j is not None:
                back, beyond = (lvl * 0.995, lvl * 1.005) if up else (lvl * 1.005, lvl * 0.995)
                for k in range(j, min(len(c), j + 5)):
                    b = c[k].h >= beyond if up else c[k].l <= beyond
                    rb = (c[k].c <= back if up else c[k].c >= back) if k == j else (c[k].l <= back if up else c[k].h >= back)
                    if b or rb:
                        reac = "dudoso" if b and rb else "sigue" if b else "rebota"
                        break
            if j is None and i + 24 > len(c):          # todavía no pasan 24 h: no cuenta aún
                print(f"{r['fecha']} {r['moneda']} {z['lado']:7} {lvl:>9,.0f}: pendiente (menos de 24 h de datos)")
                continue
            d = abs(lvl / r["precio"] - 1)
            n = h = 0
            for k in range(0, len(c) - 24, 3):
                tgt = c[k].c * (1 + d) if up else c[k].c * (1 - d)
                n += 1
                h += any((c[m].h >= tgt) if up else (c[m].l <= tgt) for m in range(k + 1, k + 25))
            base.append(h / n if n else 0)
            tot += 1
            hit24 += j is not None and j - i < 24
            print(f"{r['fecha']} {r['moneda']} {z['lado']:7} {lvl:>9,.0f} ({d:.1%}): "
                  f"{'tocada a las ' + str(j - i) + ' h' if j is not None else 'no tocada en ' + str(min(72, len(c) - i)) + ' h'} · {reac} · "
                  f"base 24 h {base[-1]:.0%}")
    if swing:
        print(f"\nSwing (1D/4H, hasta 30 días): {sum(swing)} de {len(swing)} tocadas")
    if tot:
        print(f"\n{tot} zonas · tocadas en 24 h {hit24 / tot:.0%} · nivel cualquiera a la misma distancia {sum(base) / tot:.0%}")


if __name__ == "__main__":
    main()
