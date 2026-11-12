import sys, time
sys.path.insert(0, '/home/user/Blockchain_IOT')
from statistics import fmean
from copytrading.sources.hyperliquid import HyperliquidSource
from copytrading.method.emas import ema_series
FEE = 0.0009

def manage(c, j, side, entry, stop, horizon):
    short = side == "short"; risk = abs(stop - entry)
    if risk <= 0: return None
    fee_r = FEE * entry / risk; t1 = entry - risk if short else entry + risk; t2 = entry - 2 * risk if short else entry + 2 * risk
    o, half, st = 0.0, False, stop
    for k in c[j + 1:j + 1 + horizon]:
        if (k.h >= st) if short else (k.l <= st): o = o if half else -1.0; break
        if not half and ((k.l <= t1) if short else (k.h >= t1)): half, o, st = True, 0.5, entry
        if half and ((k.l <= t2) if short else (k.h >= t2)): o = 1.5; break
    return o - fee_r

def piv(c, i, k, hi=True):
    w = c[i - k:i + k + 1]
    return c[i].h == max(x.h for x in w) if hi else c[i].l == min(x.l for x in w)

def study(c, bars_per_day, tol=0.002, dip=0.004, horizon=48, k=3, look=40, after=12):
    e50 = ema_series(c, "1d", 50); tb = 6 * bars_per_day
    out = []; i = look + tb; last = -999
    while i < len(c) - 1:
        for side in ("short", "long"):
            hi = side == "short"
            pk = [j for j in range(i - look, i - k) if piv(c, j, k, hi)]
            if len(pk) < 2: continue
            p1, p2 = pk[-2], pk[-1]
            if p2 - p1 < 5 or i - p2 > after: continue
            v1, v2 = (c[p1].h, c[p2].h) if hi else (c[p1].l, c[p2].l)
            if abs(v2 - v1) / v1 > tol: continue
            mid = c[p1:p2 + 1]
            neck = min(x.l for x in mid) if hi else max(x.h for x in mid)
            depth = (min(v1, v2) - neck) / neck if hi else (neck - max(v1, v2)) / neck
            if depth < dip: continue
            if not ((c[i].c < neck and c[i - 1].c >= neck) if hi else (c[i].c > neck and c[i - 1].c <= neck)): continue
            if i - last < 12: continue
            last = i
            if not (e50[i] and e50[i - tb]): continue
            trend = "a favor" if ((e50[i] < e50[i - tb]) == hi) else "en contra"
            stop = max(v1, v2) * 1.001 if hi else min(v1, v2) * 0.999
            vol_div = sum(x.v for x in c[p2 - 1:p2 + 2]) < sum(x.v for x in c[p1 - 1:p1 + 2])
            # A: al cierre que rompe el cuello; B: límite en el cuello (retesteo) hasta 6 velas
            ra = manage(c, i, side, c[i].c, stop, horizon)
            rb = None
            for j in range(i + 1, min(i + 7, len(c))):
                if (c[j].h >= stop) if hi else (c[j].l <= stop): break
                if (c[j].h >= neck) if hi else (c[j].l <= neck):
                    rb = manage(c, j, side, neck, stop, horizon); break
            seg = c[i + 1:i + 1 + 24]
            mfe = ((c[i].c - min(x.l for x in seg)) / c[i].c if hi else (max(x.h for x in seg) - c[i].c) / c[i].c) if seg else 0
            out.append(dict(side=side, trend=trend, ra=ra, rb=rb, vol_div=vol_div, mfe=mfe, depth=depth))
        i += 1
    return out

def base_strong(c, n=24, thr=0.015):
    hits = tot = 0
    for i in range(0, len(c) - n, 6):
        seg = c[i + 1:i + 1 + n]; tot += 1
        if max(x.h for x in seg) / c[i].c - 1 >= thr or 1 - min(x.l for x in seg) / c[i].c >= thr: hits += 1
    return hits / tot

s = HyperliquidSource(); end = int(time.time() * 1000)
for tf, ms, bpd in (("1h", 3600000, 24), ("15m", 900000, 96)):
    res = []; base = []
    for coin in ("BTC", "ETH", "SOL"):
        c = s.candles(coin, tf, end - 5000 * ms, end)
        res += study(c, bpd); base.append(base_strong(c, n=24 if tf == "1h" else 96))
    print(f"\n== {tf}: doble techo (M) / doble suelo (W) que rompe el cuello · BTC+ETH+SOL")
    print(f"   base: cualquier momento, movimiento ≥1,5 % en las 24 h siguientes: {fmean(base):.0%}")
    for trend in ("a favor", "en contra"):
        g = [r for r in res if r["trend"] == trend]
        if not g: continue
        strong = sum(r["mfe"] >= 0.015 for r in g) / len(g)
        ra = [r["ra"] for r in g if r["ra"] is not None]; rb = [r["rb"] for r in g if r["rb"] is not None]
        print(f"   {trend:9} {len(g):3} casos · siguen ≥1,5 % en 24 h: {strong:.0%} · entrada al cierre {fmean(ra):+.2f}R/op · "
              f"límite en el cuello {fmean(rb) if rb else 0:+.2f}R/op ({len(rb)} se llenan)")
        for lab, sub in (("2.º techo con MENOS volumen", [r for r in g if r["vol_div"]]), ("2.º techo con más volumen", [r for r in g if not r["vol_div"]])):
            if sub:
                ra = [r["ra"] for r in sub if r["ra"] is not None]; rb = [r["rb"] for r in sub if r["rb"] is not None]
                print(f"      {lab:28} {len(sub):3} · ≥1,5 %: {sum(r['mfe']>=0.015 for r in sub)/len(sub):.0%} · cierre {fmean(ra):+.2f}R · cuello {fmean(rb) if rb else 0:+.2f}R")
