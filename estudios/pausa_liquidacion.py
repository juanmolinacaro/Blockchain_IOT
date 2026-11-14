"""Dónde entrar después de la liquidación (idea de Juan, 13 nov 2026): "el precio cae, se frena cuando
liquida, empieza a acumular o hacer rango; ahí revisamos dónde entrar según la estructura".

Secuencia (1H, BTC+ETH+SOL, ~208 días, a favor de la tendencia por la EMA 50 diaria; y su espejo al alza):
1. **Impulso**: cae ≥ 2 % desde el máximo de las 12 velas previas hasta un mínimo de 48 velas, en ≤ 6 velas.
2. **Pausa / rango**: en las velas siguientes no hace mínimo nuevo (como mucho 0,2 % por debajo) y el rebote
   no recupera más del 60 % de la caída. El rango queda formado cuando lleva ≥ 6 velas.
3. **Entradas** (en las 24 velas siguientes), con la gestión de Juan (mitad en 1R, stop a la entrada,
   resto 2R; 48 velas; comisión 0,09 %):
   * E1 límite en el TECHO del rango (vender arriba), stop 0,2 % sobre el techo;
   * E2 al cierre que ROMPE el suelo del rango, stop sobre la mitad del rango;
   * E3 límite en el SUELO roto (retesteo tras romper), stop sobre la mitad del rango;
   * E4 trampa en el techo: la vela supera el techo y cierra dentro → límite en el techo, stop sobre la mecha.
"""
import sys, time
sys.path.insert(0, "/home/user/Blockchain_IOT")
from statistics import fmean
from copytrading.sources.hyperliquid import HyperliquidSource
from copytrading.method.emas import ema_series

FEE = 0.0009


def manage(c, j, short, entry, stop, horizon=48):
    risk = abs(stop - entry)
    if risk <= 0 or (short and stop <= entry) or (not short and stop >= entry):
        return None
    fee_r = FEE * entry / risk
    t1 = entry - risk if short else entry + risk
    t2 = entry - 2 * risk if short else entry + 2 * risk
    o, half, st = 0.0, False, stop
    for k in c[j + 1:j + 1 + horizon]:
        if (k.h >= st) if short else (k.l <= st):
            o = o if half else -1.0
            break
        if not half and ((k.l <= t1) if short else (k.h >= t1)):
            half, o, st = True, 0.5, entry
        if half and ((k.l <= t2) if short else (k.h >= t2)):
            o = 1.5
            break
    return o - fee_r, risk / entry


def mirror(c):
    from types import SimpleNamespace as C
    return [C(t=k.t, o=-k.o, h=-k.l, l=-k.h, c=-k.c, v=k.v) for k in c]


def study(c, short=True):
    """Para cortos usa las velas tal cual; para largos, el espejo (precio negado)."""
    cc = c if short else mirror(c)
    e50 = ema_series(c, "1d", 50)
    out = {}
    i = 200
    n = len(cc)
    while i < n - 30:
        hi12 = max(k.h for k in cc[i - 12:i])
        lo48 = min(k.l for k in cc[i - 48:i])
        k = cc[i]
        drop = (hi12 - k.l) / abs(hi12)
        if not (k.l < lo48 and drop >= 0.02 if short else (k.l < lo48 and (k.l - hi12) / abs(hi12) <= -0.02)):
            i += 1
            continue
        if not (e50[i] and e50[i - 144]):
            i += 1
            continue
        down = e50[i] < e50[i - 144]
        if down != short:                       # solo a favor de la tendencia
            i += 1
            continue
        low = k.l
        # extender el impulso mientras siga haciendo mínimos
        j = i
        while j + 1 < n and cc[j + 1].l < low:
            j += 1
            low = cc[j].l
        top = hi12
        # pausa: velas tras el mínimo sin mínimo nuevo y con rebote < 60 % de la caída
        m = j + 1
        rhi = cc[j].h
        ok = False
        while m < n - 1 and m - j <= 24:
            rhi = max(rhi, cc[m].h)
            if cc[m].l < low * (1 + 0.002 * (1 if low > 0 else -1)) - (0 if low > 0 else 0) and cc[m].l < low - abs(low) * 0.002:
                break                            # hizo mínimo nuevo: no es pausa
            if (rhi - low) > 0.6 * (top - low):
                break                            # recuperó demasiado: no es bandera
            if m - j >= 6:
                ok = True
                break
            m += 1
        if not ok:
            i = j + 1
            continue
        box_lo = min(x.l for x in cc[j:m + 1])
        box_hi = max(x.h for x in cc[j + 1:m + 1])
        mid = (box_lo + box_hi) / 2
        res = {}
        broke = None
        for q in range(m + 1, min(m + 25, n - 1)):
            x = cc[q]
            if "E1" not in res and x.h >= box_hi and broke is None:
                r = manage(cc, q, True, box_hi, box_hi + abs(box_hi) * 0.002)
                if r: res["E1 límite en el techo del rango"] = r
            if "E4" not in res and x.h > box_hi and x.c < box_hi and broke is None:
                r = manage(cc, q, True, x.c, x.h + abs(x.h) * 0.001)
                if r: res["E4 trampa en el techo (cierre dentro)"] = r
                res["E4"] = True
            if broke is None and x.c < box_lo:
                broke = q
                r = manage(cc, q, True, x.c, mid)
                if r: res["E2 al cierre que rompe el suelo"] = r
            elif broke is not None and "E3" not in res and x.h >= box_lo and q > broke:
                r = manage(cc, q, True, box_lo, mid)
                if r: res["E3 límite en el suelo roto (retesteo)"] = r
                res["E3"] = True
            if "E1" in res or True:
                res.setdefault("E1", "E1 límite en el techo del rango" in res)
        # E5: vender el rebote al 50 % de la caída (límite), stop sobre el 70 %; espera 48 velas
        lvl50 = low + 0.5 * (top - low)
        lvl70 = low + 0.7 * (top - low)
        for q in range(j + 1, min(j + 49, n - 1)):
            if cc[q].h >= lvl70:
                break
            if cc[q].h >= lvl50:
                r = manage(cc, q, True, lvl50, lvl70)
                if r: res["E5 límite en el 50 % del rebote"] = r
                break
        # E6: comprar el suelo del rango (contra la tendencia), stop 0,3 % bajo el mínimo de la caída
        for q in range(m + 1, min(m + 25, n - 1)):
            if cc[q].l <= box_lo:
                r = manage(cc, q, False, box_lo, low - abs(low) * 0.003)
                if r: res["E6 comprar el suelo del rango (rebote)"] = r
                break
        for name, r in res.items():
            if isinstance(r, tuple):
                out.setdefault(name, []).append(r)
        out.setdefault("_casos", []).append(1)
        i = m + 1
    return out


s = HyperliquidSource()
end = int(time.time() * 1000)
for short in (True, False):
    tot = {}
    for coin in ("BTC", "ETH", "SOL"):
        c = s.candles(coin, "1h", end - 5000 * 3600000, end)
        for k, v in study(c, short).items():
            tot.setdefault(k, []).extend(v)
    n = len(tot.get("_casos", []))
    print(f"\n== {'Caída' if short else 'Subida'} con liquidación → pausa/rango → {'corto' if short else 'largo'} (a favor de la tendencia): {n} casos")
    for name in ("E1 límite en el techo del rango", "E4 trampa en el techo (cierre dentro)",
                 "E2 al cierre que rompe el suelo", "E3 límite en el suelo roto (retesteo)",
                 "E5 límite en el 50 % del rebote", "E6 comprar el suelo del rango (rebote)"):
        rs = tot.get(name, [])
        if rs:
            print(f"  {name:40} entradas {len(rs):3} ({len(rs) / n:4.0%})  {fmean(r for r, _ in rs):+.2f}R/op  "
                  f"total {sum(r for r, _ in rs):+6.1f}R  riesgo medio {fmean(x for _, x in rs) * 100:.2f}%")
