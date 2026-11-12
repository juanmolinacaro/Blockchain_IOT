import sys, time
sys.path.insert(0, '/home/user/Blockchain_IOT')
from statistics import fmean
from copytrading.sources.hyperliquid import HyperliquidSource
from copytrading.method.emas import ema_series

FEE = 0.0009
def run_trade(c, i0, side, entry, stop, horizon=48, rule="juan"):
    short = side == "short"; risk = abs(stop - entry)
    if risk <= 0: return None
    fee_r = FEE * entry / risk
    t1 = entry - risk if short else entry + risk
    t2 = entry - 2 * risk if short else entry + 2 * risk
    o, half, st = 0.0, False, stop
    for k in c[i0 + 1:i0 + 1 + horizon]:
        if (k.h >= st) if short else (k.l <= st):
            o = o if half else -1.0; break
        if not half and ((k.l <= t1) if short else (k.h >= t1)):
            half, o, st = True, 0.5, entry
        if half and ((k.l <= t2) if short else (k.h >= t2)):
            o = 1.5; break
    return o - fee_r, risk / entry

def study(c, N=24, trend_bars=144, wait=6):
    e50 = ema_series(c, "1d", 50)
    res = {}
    i = N + trend_bars
    while i < len(c) - 2:
        k = c[i]; w = c[i - N:i]
        hh, ll = max(x.h for x in w), min(x.l for x in w)
        side = None
        if k.h > hh and k.c < hh: side, lvl, ext = "short", hh, k.h
        elif k.l < ll and k.c > ll: side, lvl, ext = "long", ll, k.l
        if not side: i += 1; continue
        if not (e50[i] and e50[i - trend_bars]): i += 1; continue
        bear = e50[i] < e50[i - trend_bars]
        fav = "a favor" if bear == (side == "short") else "en contra"
        short = side == "short"
        stop = ext * (1.001 if short else 0.999)
        # A) al cierre de la vela que vuelve dentro
        variants = {"A cierre": (i, k.c)}
        # B) límite en el nivel barrido (retesteo), esperando hasta `wait` velas
        # C) límite a mitad de la mecha (entre nivel y extremo)
        for name, px in (("B límite en el nivel", lvl), ("C límite media mecha", (lvl + ext) / 2)):
            for j in range(i + 1, min(i + 1 + wait, len(c))):
                kk = c[j]
                if (kk.h >= stop) if short else (kk.l <= stop): break
                if (kk.h >= px) if short else (kk.l <= px):
                    variants[name] = (j, px); break
        # D) confirmación de estructura: espera un máximo más bajo (vela que no supera el extremo) y entra
        #    al romper el mínimo de la vela de barrido
        trig = k.l if short else k.h
        for j in range(i + 1, min(i + 1 + wait, len(c))):
            kk = c[j]
            if (kk.h >= stop) if short else (kk.l <= stop): break
            if (kk.l < trig) if short else (kk.h > trig):
                variants["D rompe el mínimo de la vela trampa"] = (j, trig); break
        for name, (j, px) in variants.items():
            r = run_trade(c, j, side, px, stop)
            if r: res.setdefault((fav, name), []).append(r)
        res.setdefault((fav, "_señales"), []).append((0, 0))
        i += 6
    return res

s = HyperliquidSource(); end = int(time.time() * 1000)
tot = {}
for coin in ("BTC", "ETH", "SOL"):
    c = s.candles(coin, "1h", end - 5000 * 3600000, end)
    for k, v in study(c).items(): tot.setdefault(k, []).extend(v)
for fav in ("a favor", "en contra"):
    n = len(tot.get((fav, "_señales"), []))
    print(f"\n== Trampas {fav} de la tendencia: {n} señales (barre el máximo/mínimo de 24 h y vuelve a cerrar dentro)")
    for name in ("A cierre", "B límite en el nivel", "C límite media mecha", "D rompe el mínimo de la vela trampa"):
        rs = tot.get((fav, name), [])
        if rs:
            print(f"  {name:38} entradas {len(rs):3} ({len(rs)/n:4.0%})  R/op {fmean(r for r,_ in rs):+.2f}  "
                  f"total {sum(r for r,_ in rs):+6.1f}R  riesgo medio {fmean(x for _,x in rs)*100:.2f}%")

# ---- ¿ayuda la estructura? ubicación del nivel barrido en el canal de regresión de 48 velas
from statistics import pstdev
def chan_pos(c, i, px, n=48):
    ys = [k.c for k in c[i - n:i]]; xs = list(range(n)); mx, my = fmean(xs), fmean(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs); a = my - b * mx
    sd = pstdev([y - (a + b * x) for x, y in zip(xs, ys)]) or 1e-9
    lo, hi = a + b * n - 2 * sd, a + b * n + 2 * sd
    return (px - lo) / (hi - lo)
print("\n== Entrada B (límite en el nivel), según dónde está el nivel barrido en el canal de 1H")
grp = {}
for coin in ("BTC", "ETH", "SOL"):
    c = s.candles(coin, "1h", end - 5000 * 3600000, end)
    i = 24 + 144
    while i < len(c) - 2:
        k = c[i]; w = c[i - 24:i]; hh, ll = max(x.h for x in w), min(x.l for x in w)
        side = "short" if (k.h > hh and k.c < hh) else "long" if (k.l < ll and k.c > ll) else None
        if not side: i += 1; continue
        lvl, ext = (hh, k.h) if side == "short" else (ll, k.l)
        short = side == "short"; stop = ext * (1.001 if short else 0.999)
        pos = chan_pos(c, i, lvl)
        good = (pos >= 0.6) if short else (pos <= 0.4)
        bad = (pos <= 0.4) if short else (pos >= 0.6)
        tag = "a favor de la estructura (corto arriba / largo abajo)" if good else "en contra (corto abajo / largo arriba)" if bad else "mitad del canal"
        for j in range(i + 1, min(i + 7, len(c))):
            kk = c[j]
            if (kk.h >= stop) if short else (kk.l <= stop): break
            if (kk.h >= lvl) if short else (kk.l <= lvl):
                r = run_trade(c, j, side, lvl, stop)
                if r: grp.setdefault(tag, []).append(r[0])
                break
        i += 6
for k, v in grp.items(): print(f"  {k:52} {len(v):3} entradas  R/op {fmean(v):+.2f}  total {sum(v):+.1f}R")
