"""Estudio del ciclo de vida de los pools de liquidez (sobre el mapa estimado).

Responde con datos a las preguntas del método:
  * Tiempo de carga: cuánto tarda un pool en volverse relevante.
  * Tiempo hasta la liquidación: cuánto tarda el precio en ir a buscarlo (y cuántos nunca se tocan).
  * Fuerza del rebote: cuánto rebota el precio tras barrerlo y cuánto se pasa antes de girar.
  * Trampas: si antes de barrer el pool grande el precio hace un falso movimiento al lado
    contrario (barre shorts arriba y rechaza), y si esa trampa anticipa el barrido.
  * Efecto imán: si el precio va antes al pool más grande aunque esté más lejos.

Un "pool" es un pico de concentración del mapa (una franja roja): densidad al menos `peak_mult`
veces la mediana del mapa, ancho máximo ±`max_half_bins` niveles y tamaño de al menos `min_size`
veces el volumen medio por vela. Se considera liquidado cuando el
precio llega a su centro ponderado.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..models import Candle
from .channels import regression_channel
from .emas import ema_series
from .liqmodel import LiquidationModel


@dataclass
class Zone:
    side: str          # "long" (debajo del precio) | "short" (encima)
    lo_bin: int
    hi_bin: int
    size: float        # USD / volumen medio por vela
    center: float      # precio medio ponderado
    born_t: float      # momento medio en que se cargó su liquidez (ponderado por USD)


@dataclass
class Pool:
    side: str
    born_i: int                 # vela en la que superó el umbral (se vuelve "relevante")
    born_t: int                 # hora de esa vela (ms)
    first_t: float              # momento medio en que se cargó su liquidez
    center: float
    lo_bin: int
    hi_bin: int
    size_birth: float
    peak_size: float
    dist_birth: float           # distancia al precio al nacer (fracción)
    swept_i: int | None = None
    end: str = "abierto"        # "liquidado" | "disuelto" | "abierto"
    # reacción tras el barrido (se rellena después)
    bounce: dict[int, float] = field(default_factory=dict)     # horizonte (velas) -> rebote máximo
    overshoot: dict[int, float] = field(default_factory=dict)  # horizonte -> cuánto se pasó del centro
    reclaimed: bool = False     # la vela del barrido cerró de vuelta (mecha de rechazo)
    trap: bool = False          # antes del barrido hubo una trampa al lado contrario
    ema_conf: bool = False
    channel_conf: bool = False


@dataclass
class StudyConfig:
    min_size: float = 5.0           # tamaño mínimo para ser un pool (en velas de volumen)
    peak_mult: float = 2.5          # el pico debe ser 2,5x la densidad mediana del mapa
    max_half_bins: int = 3          # ancho máximo de la zona: ±3 niveles (±0,75 %)
    merge_bins: int = 2             # tolerancia al comparar un pool nuevo con uno vivo
    dissolve: float = 0.3           # un pool se da por disuelto si conserva < 30 % de su máximo
    max_dist: float = 0.10          # solo pools a menos del 10 % del precio
    half_life_bars: float = 336     # 14 días en velas de 1H
    vol_window: int = 50
    horizons: tuple[int, ...] = (8, 24, 72)   # en velas
    trap_window: int = 48           # velas antes del barrido donde buscar la trampa
    trap_sweep: float = 2.0         # liquidez contraria absorbida mínima (≈ el 5 % de velas más fuertes)
    forward: int = 72               # velas para medir "qué pool se toca primero"
    sample_every: int = 6
    conf_pct: float = 0.015


def config_for(bar_hours: float, **kw) -> StudyConfig:
    """Misma configuración en horas reales para cualquier temporalidad (1h, 4h...)."""
    bars = lambda h: max(1, round(h / bar_hours))
    base = dict(half_life_bars=336 / bar_hours, horizons=(bars(8), bars(24), bars(72)),
                trap_window=bars(48), forward=bars(72), sample_every=bars(6))
    base.update(kw)
    return StudyConfig(**base)


def merge(results: list[StudyResult]) -> StudyResult:
    """Une varios estudios (misma temporalidad) para tener más casos."""
    return StudyResult([p for r in results for p in r.pools], results[0].bar_ms,
                       [m for r in results for m in r.magnet],
                       [e for r in results for e in r.trap_events],
                       [e for r in results for e in r.base_events])


def _zones(model: LiquidationModel, side: str, price: float, avg: float, cfg: StudyConfig) -> list[Zone]:
    """Zonas "rojas": picos de concentración del mapa (como las franjas más intensas del heatmap)."""
    book = model.longs if side == "long" else model.shorts
    lo_b, hi_b = model._bin(price * (1 - cfg.max_dist)), model._bin(price * (1 + cfg.max_dist))
    raw = [book.get(b, 0.0) for b in range(lo_b, hi_b + 1)]
    n = len(raw)
    sm = [sum(raw[max(0, k - 1):k + 2]) / len(raw[max(0, k - 1):k + 2]) for k in range(n)]
    nonzero = sorted(v for v in sm if v > 0)
    if not nonzero:
        return []
    med = nonzero[len(nonzero) // 2]
    peaks = [k for k in range(n) if sm[k] >= cfg.peak_mult * med
             and (k == 0 or sm[k] >= sm[k - 1]) and (k == n - 1 or sm[k] > sm[k + 1])]
    out, used = [], set()
    for k in sorted(peaks, key=lambda k: sm[k], reverse=True):
        if k in used:
            continue
        lo = hi = k
        while lo - 1 >= 0 and k - lo < cfg.max_half_bins and sm[lo - 1] >= 0.5 * sm[k] and lo - 1 not in used:
            lo -= 1
        while hi + 1 < n and hi - k < cfg.max_half_bins and sm[hi + 1] >= 0.5 * sm[k] and hi + 1 not in used:
            hi += 1
        used.update(range(lo, hi + 1))
        amt = sum(raw[lo:hi + 1])
        if amt <= 0 or amt / avg < cfg.min_size:
            continue
        bins = [lo_b + j for j in range(lo, hi + 1) if raw[j] > 0]
        center = sum(model.price_of(b) * book[b] for b in bins) / amt
        out.append(Zone(side, lo_b + lo, lo_b + hi, amt / avg, center, model.mean_time(side, bins)))
    return out


@dataclass
class StudyResult:
    pools: list[Pool]
    bar_ms: int
    magnet: list[dict]          # muestras: tamaños, distancias y cuál se tocó primero
    trap_events: list[dict]     # trampas (barrido contrario + rechazo) y si luego se barrió el pool grande
    base_events: list[dict]     # mismas condiciones sin trampa (comparación)


def study(candles: list[Candle], cfg: StudyConfig | None = None) -> StudyResult:
    cfg = cfg or StudyConfig()
    bar_ms = candles[1].t - candles[0].t
    model = LiquidationModel(decay_per_bar=0.5 ** (1 / cfg.half_life_bars))
    open_pools: list[Pool] = []
    pools: list[Pool] = []
    usd_hist: list[float] = []
    sweeps: list[tuple[float, float]] = []
    snapshots: list[tuple[list[Zone], list[Zone]]] = []

    for i, c in enumerate(candles):
        sl, ss = model.update(c)
        usd_hist.append(c.v * c.c)
        win = usd_hist[-cfg.vol_window:]
        avg = sum(win) / len(win) or 1.0
        sweeps.append((sl / avg, ss / avg))

        # 1) ¿se liquidó algún pool abierto en esta vela?
        for p in list(open_pools):
            hit = c.l <= p.center if p.side == "long" else c.h >= p.center
            if hit:
                p.swept_i, p.end = i, "liquidado"
                p.reclaimed = c.c > p.center if p.side == "long" else c.c < p.center
                open_pools.remove(p)

        longs = _zones(model, "long", c.c, avg, cfg)
        shorts = _zones(model, "short", c.c, avg, cfg)
        snapshots.append((longs, shorts))

        # 2) seguir los pools vivos (su liquidez sigue en el mapa) y detectar nuevos
        current = longs + shorts
        for p in list(open_pools):
            book = model.longs if p.side == "long" else model.shorts
            bins = [b for b in range(p.lo_bin, p.hi_bin + 1) if b in book]
            amt = sum(book[b] for b in bins) / avg
            if amt < cfg.dissolve * p.peak_size:
                p.end = "disuelto"
                open_pools.remove(p)
                continue
            p.peak_size = max(p.peak_size, amt)
            p.center = sum(model.price_of(b) * book[b] for b in bins) / (amt * avg)
        for z in current:
            known = any(p.side == z.side and z.lo_bin <= p.hi_bin + cfg.merge_bins
                        and z.hi_bin >= p.lo_bin - cfg.merge_bins for p in open_pools)
            if not known:
                p = Pool(z.side, i, c.t, z.born_t, z.center, z.lo_bin, z.hi_bin, z.size, z.size,
                         abs(z.center / c.c - 1))
                open_pools.append(p)
                pools.append(p)

    _post_sweep(candles, pools, sweeps, cfg)
    magnet = _magnet(candles, snapshots, cfg)
    traps, base = _traps(candles, snapshots, sweeps, cfg)
    return StudyResult(pools, bar_ms, magnet, traps, base)


def _post_sweep(candles: list[Candle], pools: list[Pool], sweeps: list[tuple[float, float]],
                cfg: StudyConfig) -> None:
    n = len(candles)
    ema200 = ema_series(candles, "1d", 200)
    ema50 = ema_series(candles, "1d", 50)
    for p in pools:
        if p.swept_i is None:
            continue
        s = p.swept_i
        long = p.side == "long"
        for h in cfg.horizons:
            if s + h >= n:
                continue
            seg = candles[s + 1:s + h + 1]
            if long:   # pool de longs barrido: esperamos rebote al alza
                p.bounce[h] = max(x.h for x in seg) / p.center - 1
                p.overshoot[h] = 1 - min(x.l for x in candles[s:s + h + 1]) / p.center
            else:
                p.bounce[h] = 1 - min(x.l for x in seg) / p.center
                p.overshoot[h] = max(x.h for x in candles[s:s + h + 1]) / p.center - 1
        # trampa: antes del barrido el precio absorbió liquidez del lado contrario
        lo = max(0, s - cfg.trap_window)
        opp = [sweeps[j][1] if long else sweeps[j][0] for j in range(lo, s)]
        p.trap = any(v >= cfg.trap_sweep for v in opp)
        emas = [e for e in (ema200[s], ema50[s]) if e]
        p.ema_conf = any(abs(e / p.center - 1) <= cfg.conf_pct for e in emas)
        ch = regression_channel(candles, s, 60)
        if ch:
            border = ch.lower(s) if long else ch.upper(s)
            p.channel_conf = abs(border / p.center - 1) <= cfg.conf_pct


def _first_touch(candles: list[Candle], i: int, below: float, above: float, forward: int) -> str:
    for c in candles[i + 1:i + 1 + forward]:
        hit_b, hit_a = c.l <= below, c.h >= above
        if hit_b and hit_a:
            return "ambos"
        if hit_b:
            return "abajo"
        if hit_a:
            return "arriba"
    return "ninguno"


def _magnet(candles: list[Candle], snapshots, cfg: StudyConfig) -> list[dict]:
    out = []
    for i in range(0, len(candles) - cfg.forward, cfg.sample_every):
        longs, shorts = snapshots[i]
        px = candles[i].c
        below = [z for z in longs if z.center < px]
        above = [z for z in shorts if z.center > px]
        if not below or not above:
            continue
        b = max(below, key=lambda z: z.center)   # el más cercano por debajo
        a = min(above, key=lambda z: z.center)   # el más cercano por encima
        res = _first_touch(candles, i, b.center, a.center, cfg.forward)
        if res in ("ambos", "ninguno"):
            continue
        out.append({"size_below": b.size, "size_above": a.size,
                    "dist_below": 1 - b.center / px, "dist_above": a.center / px - 1, "first": res})
    return out


def _traps(candles: list[Candle], snapshots, sweeps, cfg: StudyConfig) -> tuple[list[dict], list[dict]]:
    """Trampa al alza: la vela absorbe shorts y cierra en su mitad baja (rechazo), con un pool de longs
    debajo mayor que el de shorts que queda arriba. ¿Se barre luego el pool de abajo? (y simétrico)."""
    traps, base = [], []
    for i in range(len(candles) - cfg.forward):
        longs, shorts = snapshots[i]
        c = candles[i]
        px = c.c
        below = [z for z in longs if z.center < px]
        above = [z for z in shorts if z.center > px]
        if not below or not above:
            continue
        b = max(below, key=lambda z: z.center)
        a = min(above, key=lambda z: z.center)
        rng = (c.h - c.l) or 1e-9
        for side, big, small, opp_sweep, rejected in (
            ("long", b, a, sweeps[i][1], (c.c - c.l) / rng < 0.5),    # trampa arriba, objetivo abajo
            ("short", a, b, sweeps[i][0], (c.h - c.c) / rng < 0.5),   # trampa abajo, objetivo arriba
        ):
            if big.size < 1.5 * small.size:
                continue
            target = big.center
            hit = None
            for k, x in enumerate(candles[i + 1:i + 1 + cfg.forward], 1):
                if (x.l <= target) if side == "long" else (x.h >= target):
                    hit = k
                    break
            ev = {"side": side, "hit": hit is not None, "bars": hit,
                  "dist": abs(target / px - 1), "ratio": big.size / small.size}
            (traps if opp_sweep >= cfg.trap_sweep and rejected else base).append(ev)
    return traps, base


# ------------------------------------------------------------------ informe
def _pct(vals: list[float], q: float) -> float:
    s = sorted(vals)
    return s[min(int(q * len(s)), len(s) - 1)] if s else 0.0


def report(name: str, res: StudyResult, cfg: StudyConfig | None = None) -> list[str]:
    cfg = cfg or StudyConfig()
    hrs = res.bar_ms / 3_600_000
    P = res.pools
    swept = [p for p in P if p.end == "liquidado"]
    L = [f"## {name}", ""]
    if not P:
        return L + ["Sin pools."]
    # tiempo de carga: edad media de la liquidez del pool cuando se vuelve relevante
    load = [(p.born_t - p.first_t) / 3_600_000 for p in P if p.first_t]
    to_sweep = [(p.swept_i - p.born_i) * hrs for p in swept]
    L.append(f"Pools detectados: {len(P)} · liquidados {len(swept)} ({len(swept) / len(P):.0%}) · "
             f"disueltos {sum(p.end == 'disuelto' for p in P)} · abiertos {sum(p.end == 'abierto' for p in P)}")
    L.append("")
    L.append("**Tiempo de carga** (edad media de su liquidez cuando se vuelve relevante): "
             f"mediana {statistics.median(load):.0f} h, la mitad entre {_pct(load, .25):.0f} y {_pct(load, .75):.0f} h")
    if to_sweep:
        L.append("**Tiempo hasta la liquidación** (desde que es relevante): "
                 f"mediana {statistics.median(to_sweep):.0f} h, la mitad entre {_pct(to_sweep, .25):.0f} y "
                 f"{_pct(to_sweep, .75):.0f} h")
        for lim in (24, 72, 168):
            share = sum(t <= lim for t in to_sweep) / len(P)
            L.append(f"  · liquidados en menos de {lim} h: {share:.0%} de todos los pools")
        near = [p for p in P if p.dist_birth <= 0.02]
        far = [p for p in P if p.dist_birth > 0.04]
        if near and far:
            L.append(f"  · por distancia al nacer: a <2 % se liquida el {sum(p.end == 'liquidado' for p in near) / len(near):.0%}; "
                     f"a >4 % el {sum(p.end == 'liquidado' for p in far) / len(far):.0%}")
        big = [p for p in P if p.peak_size >= _pct([q.peak_size for q in P], 0.8)]
        L.append(f"  · los pools más grandes (top 20 %) se liquidan el {sum(p.end == 'liquidado' for p in big) / len(big):.0%} de las veces")
    L.append("")
    L.append("**Rebote tras el barrido** (desde el centro del pool):")
    L.append("| Horizonte | Rebote mediano | Rebote ≥1 % | Rebote ≥2 % | Se pasa del centro (mediana) |")
    L.append("|---|---|---|---|---|")
    for h in cfg.horizons:
        b = [p.bounce[h] for p in swept if h in p.bounce]
        o = [p.overshoot[h] for p in swept if h in p.overshoot]
        if b:
            L.append(f"| {h * hrs:.0f} h | {statistics.median(b):.1%} | {sum(x >= .01 for x in b) / len(b):.0%} | "
                     f"{sum(x >= .02 for x in b) / len(b):.0%} | {statistics.median(o):.1%} |")
    h = cfg.horizons[1]
    for label, cond in (("con mecha de rechazo (cierra de vuelta)", lambda p: p.reclaimed),
                        ("sin rechazo (cierra más allá)", lambda p: not p.reclaimed),
                        ("con confluencia EMA 50/200 diaria", lambda p: p.ema_conf),
                        ("con confluencia borde de canal", lambda p: p.channel_conf),
                        ("con trampa previa al lado contrario", lambda p: p.trap),
                        ("sin trampa previa", lambda p: not p.trap)):
        grp = [p.bounce[h] for p in swept if h in p.bounce and cond(p)]
        if len(grp) >= 5:
            L.append(f"  · {label}: {len(grp)} casos, rebote mediano a {h * hrs:.0f} h {statistics.median(grp):.1%}, "
                     f"≥2 % el {sum(x >= .02 for x in grp) / len(grp):.0%}")
    L.append("")
    trap_share = sum(p.trap for p in swept) / len(swept) if swept else 0
    L.append(f"**Trampas**: el {trap_share:.0%} de los barridos tuvo antes (≤{cfg.trap_window * hrs:.0f} h) "
             "una absorción de liquidez al lado contrario.")
    for side, label in (("long", "trampa al alza → barrido de longs abajo"),
                        ("short", "trampa a la baja → barrido de shorts arriba")):
        t = [e for e in res.trap_events if e["side"] == side]
        b = [e for e in res.base_events if e["side"] == side]
        if len(t) >= 5 and b:
            ht, hb = sum(e["hit"] for e in t) / len(t), sum(e["hit"] for e in b) / len(b)
            bars = [e["bars"] * hrs for e in t if e["hit"]]
            L.append(f"  · {label}: tras la trampa se barre el pool grande en ≤{cfg.forward * hrs:.0f} h el "
                     f"**{ht:.0%}** ({len(t)} casos) vs {hb:.0%} sin trampa"
                     + (f"; tarda una mediana de {statistics.median(bars):.0f} h" if bars else ""))
    L.append("")
    M = res.magnet
    if M:
        bigger_first = [m for m in M if (m["first"] == "abajo") == (m["size_below"] > m["size_above"])]
        closer_first = [m for m in M if (m["first"] == "abajo") == (m["dist_below"] < m["dist_above"])]
        conflict = [m for m in M if (m["size_below"] > m["size_above"]) != (m["dist_below"] < m["dist_above"])]
        big_far = [m for m in conflict if (m["first"] == "abajo") == (m["size_below"] > m["size_above"])]
        L.append(f"**Efecto imán** ({len(M)} muestras): el precio toca antes el pool más grande el "
                 f"{len(bigger_first) / len(M):.0%} de las veces y el más cercano el {len(closer_first) / len(M):.0%}.")
        if conflict:
            L.append(f"  · cuando el grande está más lejos ({len(conflict)} casos), va primero al grande el "
                     f"**{len(big_far) / len(conflict):.0%}**")
        ratio = [m for m in M if max(m["size_below"], m["size_above"]) >= 2 * min(m["size_below"], m["size_above"])]
        if ratio:
            rb = [m for m in ratio if (m["first"] == "abajo") == (m["size_below"] > m["size_above"])]
            L.append(f"  · con un pool ≥2x mayor que el otro ({len(ratio)} casos), va primero al grande el {len(rb) / len(ratio):.0%}")
    return L
