"""¿Qué ventaja da cada dato del radar? (13 nov 2026)

Juan: "no es lo que yo diga; es ir tomando los datos que tenemos y medir qué ventaja nos da esta
información". Con los datos por minuto de la escucha (hft_flujo + binance_minuto) se mide, para cada dato,
si anticipa el movimiento del precio en los 60 y 240 minutos siguientes:

* se toma una muestra cada 15 minutos (para no contar casi lo mismo muchas veces);
* cada dato se divide en tres partes iguales (bajo / medio / alto) y se compara qué hizo el precio después
  cuando el dato estaba ALTO frente a cuando estaba BAJO: subida media y % de veces que subió;
* "ventaja" = diferencia de la subida media entre alto y bajo (en puntos básicos, 1 pb = 0,01 %), con un
  t aproximado (|t| ≥ 2 sugiere que no es casualidad; con datos solapados, es optimista).
"""
import csv, sys
from datetime import datetime, timedelta
from math import sqrt
from pathlib import Path
from statistics import fmean, pstdev

D = Path(sys.argv[1] if len(sys.argv) > 1 else "data/escucha_pc/2026-11-12")
COIN = sys.argv[2] if len(sys.argv) > 2 else "BTC"


def rows(p, coin):
    out = {}
    with p.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("moneda") == coin:
                out[datetime.strptime(r["hora_col"][:16], "%Y-%m-%d %H:%M")] = r
    return out


f = lambda r, k: float(r.get(k) or 0) if r else 0.0
fl = rows(D / "hft_flujo.csv", COIN)
bn = rows(D / "binance_minuto.csv", COIN)
times = sorted(fl)
px = {t: f(fl[t], "precio") for t in times if f(fl[t], "precio")}


def window(t, minutes, fn, src):
    vals = [fn(src.get(t - timedelta(minutes=m))) for m in range(minutes)]
    return sum(vals)


def at(t, minutes_ahead):
    t2 = t + timedelta(minutes=minutes_ahead)
    for d in range(3):
        if t2 + timedelta(minutes=d) in px:
            return px[t2 + timedelta(minutes=d)]
    return None


samples = []
for t in times[::15]:
    if t not in px or t - timedelta(minutes=60) not in px:
        continue
    b0, b60 = bn.get(t), bn.get(t - timedelta(minutes=60))
    feats = {
        "público: empuje neto 60 min": window(t, 60, lambda r: f(r, "otros_compra") - f(r, "otros_venta"), fl),
        "ganadoras: empuje neto 60 min": window(t, 60, lambda r: f(r, "ganadoras_compra") - f(r, "ganadoras_venta"), fl),
        "creadores: libro compras/ventas ±1%": (f(fl[t], "liq_creadores_compra_1pct") + 1) / (f(fl[t], "liq_creadores_venta_1pct") + 1),
        "Binance: empuje agresivo 60 min": window(t, 60, lambda r: f(r, "compra_agresiva_usd") - f(r, "venta_agresiva_usd"), bn),
        "Binance: liq. largos 60 min": window(t, 60, lambda r: f(r, "liq_largos_usd"), bn),
        "Binance: liq. cortos 60 min": window(t, 60, lambda r: f(r, "liq_cortos_usd"), bn),
        "Binance: cambio interés abierto 60 min": (f(b0, "interes_abierto") / f(b60, "interes_abierto") - 1) if b0 and b60 and f(b60, "interes_abierto") else None,
        "Binance: largos/cortos cuentas": f(b0, "cuentas_largos_cortos") if b0 else None,
        "Binance: largos/cortos top traders": f(b0, "top_traders_largos_cortos") if b0 else None,
        "Binance: funding": f(b0, "funding") if b0 else None,
        "precio: cambio últimos 60 min": px[t] / px[t - timedelta(minutes=60)] - 1,
    }
    fut = {h: (at(t, h) / px[t] - 1) if at(t, h) else None for h in (60, 240)}
    samples.append((t, feats, fut))

print(f"{COIN}: {len(samples)} muestras cada 15 min, {samples[0][0]:%d %b %H:%M} → {samples[-1][0]:%d %b %H:%M}\n")
print(f"{'dato':40} {'h':>4} {'n':>4} {'bajo: sube%/media':>18} {'alto: sube%/media':>18} {'ventaja':>9} {'t':>5}")
for name in samples[0][1]:
    for h in (60, 240):
        data = [(s[1][name], s[2][h]) for s in samples if s[1][name] is not None and s[2][h] is not None]
        if len(data) < 30:
            continue
        data.sort(key=lambda x: x[0])
        k = len(data) // 3
        lo, hi = [y for _, y in data[:k]], [y for _, y in data[-k:]]
        diff = fmean(hi) - fmean(lo)
        se = sqrt(pstdev(hi) ** 2 / len(hi) + pstdev(lo) ** 2 / len(lo)) or 1e-9
        t = diff / se
        up = lambda xs: sum(x > 0 for x in xs) / len(xs)
        flag = " ◀" if abs(t) >= 2 else ""
        print(f"{name:40} {h:4} {len(data):4} {up(lo):7.0%} {fmean(lo) * 1e4:+7.1f}pb  {up(hi):7.0%} {fmean(hi) * 1e4:+7.1f}pb "
              f"{diff * 1e4:+7.1f}pb {t:+5.1f}{flag}")
