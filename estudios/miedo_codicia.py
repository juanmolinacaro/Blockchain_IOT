"""Índice de miedo y codicia (alternative.me) para comprar y vender BTC en spot (20 nov 2026).

Pregunta de Juan: "cuando está en miedo extremo hay que comprar y cuando sube a codicia hay que vender; esto sería
para comprar en spot". Se mide con el precio diario de BTC (Hyperliquid, desde ago 2020):
1) qué hizo el precio 30, 90, 180 y 365 días después de cada día en miedo extremo (y cuánto bajó antes de subir);
2) estrategias en spot frente a comprar y mantener y frente a comprar lo mismo cada semana (DCA).
Uso: python estudios/miedo_codicia.py RUTA_fng.json   (https://api.alternative.me/fng/?limit=0&format=json)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copytrading.sources.hyperliquid import HyperliquidSource   # noqa: E402


def load(path):
    d = json.load(open(path))["data"]
    return {datetime.fromtimestamp(int(x["timestamp"]), timezone.utc).date(): int(x["value"]) for x in d}


def prices():
    c = HyperliquidSource().candles("BTC", "1d", 0, int(time.time() * 1000))
    return {datetime.fromtimestamp(k.t / 1000, timezone.utc).date(): k.c for k in c}


def forward(days, px, fng, cond, horizons=(30, 90, 180, 365)):
    out = {h: [] for h in horizons}
    dd = []
    last = None
    for i, d in enumerate(days):
        if not cond(fng.get(d, 50)):
            continue
        if last is not None and i - last < 7:            # un caso por racha (al menos 7 días entre casos)
            last = i
            continue
        last = i
        for h in horizons:
            if i + h < len(days):
                out[h].append(px[days[i + h]] / px[d] - 1)
        w = [px[x] for x in days[i:i + 90]]
        dd.append(min(w) / px[d] - 1)
    return out, dd


def backtest(days, px, fng, buy, sell):
    cash, btc, trades = 1.0, 0.0, 0
    for d in days:
        v = fng.get(d)
        if v is None:
            continue
        if cash > 0 and v <= buy:
            btc, cash, trades = cash / px[d] * (1 - 0.001), 0.0, trades + 1
        elif btc > 0 and v >= sell:
            cash, btc, trades = btc * px[d] * (1 - 0.001), 0.0, trades + 1
    final = cash + btc * px[days[-1]]
    return final, trades, btc > 0


def dca(days, px, fng, rule):
    """Compra semanal de $1 (o $2/$0 según la regla); devuelve valor final / dinero puesto."""
    spent = btc = 0.0
    for i, d in enumerate(days):
        if i % 7:
            continue
        amt = rule(fng.get(d, 50))
        spent += amt
        btc += amt / px[d]
    return btc * px[days[-1]] / spent if spent else 0.0, spent


def main(path):
    fng, px = load(path), prices()
    days = sorted(d for d in px if d in fng)
    print(f"Datos: {days[0]} → {days[-1]} ({len(days)} días) · índice hoy {fng[max(fng)]} · BTC {px[days[-1]]:,.0f}\n")
    for lab, cond in (("miedo extremo (≤ 20)", lambda v: v <= 20), ("≤ 12 (como hoy)", lambda v: v <= 12),
                      ("codicia extrema (≥ 80)", lambda v: v >= 80)):
        f, dd = forward(days, px, fng, cond)
        print(f"{lab}: {len(dd)} rachas")
        for h, v in f.items():
            if v:
                print(f"   a {h:3} días: mediana {median(v):+.0%} · subió en {sum(x > 0 for x in v)}/{len(v)}")
        if dd:
            print(f"   bajó más en los 90 días siguientes: mediana {median(dd):+.0%}, peor {min(dd):+.0%}")
    hold = px[days[-1]] / px[days[0]]
    print(f"\nComprar y mantener desde {days[0]}: ×{hold:.2f}")
    for b, s in ((20, 75), (20, 80), (25, 75), (25, 80), (20, 90), (15, 75)):
        final, n, inside = backtest(days, px, fng, b, s)
        print(f"  Compra ≤ {b}, vende ≥ {s}: ×{final:.2f} · {n} operaciones · {'dentro' if inside else 'fuera'} hoy")
    base = dca(days, px, fng, lambda v: 1.0)
    fear = dca(days, px, fng, lambda v: 2.0 if v <= 25 else 1.0 if v < 75 else 0.0)
    only = dca(days, px, fng, lambda v: 1.0 if v <= 25 else 0.0)
    print(f"\nCompra semanal (DCA): ×{base[0]:.2f} sobre lo invertido")
    print(f"  DCA doble en miedo (≤ 25), nada en codicia (≥ 75): ×{fear[0]:.2f}")
    print(f"  Solo comprar en miedo (≤ 25): ×{only[0]:.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
