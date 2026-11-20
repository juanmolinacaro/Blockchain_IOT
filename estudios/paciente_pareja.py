"""¿Cómo maneja El Paciente sus operaciones en pareja (BTC contra ETH)? (20 nov 2026)

Pregunta de Juan: "abre long y short, se va a favor de la que gana y la otra la cierra con pequeñas pérdidas?".
Las operaciones sueltas de esta cuenta solo se guardan unas horas (hace miles al día), pero los pagos de funding
traen el tamaño de cada posición: cada día (hasta hace ~2 semanas) y cada hora (las últimas ~2 semanas). Con eso
se reconstruye su posición en BTC y ETH desde oct 2025 y, con el precio, la ganancia de cada pata (aprox.:
tamaño al inicio de cada tramo × cambio de precio del tramo).

Episodio en pareja: tramos seguidos con BTC y ETH en lados opuestos, cada pata > $300k.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copytrading.sources.hyperliquid import HyperliquidSource   # noqa: E402

COT = timezone(timedelta(hours=-5))
ACCOUNT = "0xfc667adba8d4837586078f4fdcdc29804337ca06"
MIN_LEG = 300_000


def post(b):
    r = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=30))


def positions() -> dict[int, dict[str, float]]:
    now, t, out = int(time.time() * 1000), int(time.time() * 1000) - 400 * 86_400_000, {}
    while t < now:
        f = post({"type": "userFunding", "user": ACCOUNT, "startTime": t, "endTime": now})
        if not f:
            break
        for x in f:
            d = x["delta"]
            if d["coin"] in ("BTC", "ETH"):
                out.setdefault(x["time"] // 3_600_000 * 3_600_000, {})[d["coin"]] = float(d["szi"])
        nt = max(x["time"] for x in f) + 1
        if nt <= t:
            break
        t = nt
        time.sleep(0.2)
    return out


def prices(coin: str, start: int) -> dict[int, float]:
    src, now, out, t = HyperliquidSource(), int(time.time() * 1000), {}, start
    while t < now:
        part = src.candles(coin, "1h", t, now)
        if not part:
            break
        for c in part:
            out[c.t + 3_600_000] = c.c                 # cierre de la hora = precio en el instante del funding
        if part[-1].t + 1 <= t:
            break
        t = part[-1].t + 1
    return out


def main() -> None:
    pos = positions()
    ts = sorted(pos)
    px = {c: prices(c, ts[0] - 3_600_000) for c in ("BTC", "ETH")}

    def p(c, t):
        for d in range(0, 4):
            v = px[c].get(t - d * 3_600_000)
            if v:
                return v
        return None

    eps, cur = [], None
    for a, b in zip(ts, ts[1:]):
        sb, se = pos[a].get("BTC", 0.0), pos[a].get("ETH", 0.0)
        pa = {c: p(c, a) for c in ("BTC", "ETH")}
        pb = {c: p(c, b) for c in ("BTC", "ETH")}
        if None in pa.values() or None in pb.values():
            continue
        nb, ne = sb * pa["BTC"], se * pa["ETH"]
        pair = sb * se < 0 and abs(nb) > MIN_LEG and abs(ne) > MIN_LEG
        if pair:
            if cur is None:
                cur = {"start": a, "btc_side": "corto" if sb < 0 else "largo", "pnl": {"BTC": 0.0, "ETH": 0.0},
                       "max": {"BTC": 0.0, "ETH": 0.0}, "first": {"BTC": abs(nb), "ETH": abs(ne)}}
            cur["pnl"]["BTC"] += sb * (pb["BTC"] - pa["BTC"])
            cur["pnl"]["ETH"] += se * (pb["ETH"] - pa["ETH"])
            cur["max"]["BTC"] = max(cur["max"]["BTC"], abs(nb))
            cur["max"]["ETH"] = max(cur["max"]["ETH"], abs(ne))
            cur["end"], cur["last"] = b, {"BTC": abs(nb), "ETH": abs(ne)}
        elif cur:
            eps.append(cur)
            cur = None
    if cur:
        eps.append(cur)

    print(f"Posiciones desde {datetime.fromtimestamp(ts[0] / 1000, COT):%Y-%m-%d} · {len(eps)} episodios en pareja\n")
    stats = {"gana_mas_grande": 0, "perdedora_reducida": 0, "n": 0, "ganancia": 0.0, "perdida": 0.0, "total": 0.0}
    for e in eps:
        days = (e["end"] - e["start"]) / 86_400_000
        if days < 1:
            continue
        w, l = ("BTC", "ETH") if e["pnl"]["BTC"] >= e["pnl"]["ETH"] else ("ETH", "BTC")
        tot = e["pnl"]["BTC"] + e["pnl"]["ETH"]
        stats["n"] += 1
        stats["total"] += tot
        stats["ganancia"] += max(e["pnl"][w], 0)
        stats["perdida"] += min(e["pnl"][l], 0)
        bigger = max(("BTC", "ETH"), key=lambda c: e["max"][c])
        stats["gana_mas_grande"] += bigger == w
        reduced = e["last"][l] < 0.6 * e["max"][l]
        stats["perdedora_reducida"] += reduced
        print(f"{datetime.fromtimestamp(e['start'] / 1000, COT):%Y-%m-%d} → {datetime.fromtimestamp(e['end'] / 1000, COT):%m-%d} "
              f"({days:4.0f} d) BTC {e['btc_side']:5} máx ${e['max']['BTC'] / 1e6:5.1f}M {e['pnl']['BTC'] / 1e6:+6.2f}M · "
              f"ETH máx ${e['max']['ETH'] / 1e6:5.1f}M {e['pnl']['ETH'] / 1e6:+6.2f}M · total {tot / 1e6:+6.2f}M · "
              f"la pata grande {'GANA' if bigger == w else 'pierde'} · perdedora {'reducida' if reduced else 'se mantuvo'}")
    n = stats["n"] or 1
    print(f"\n{stats['n']} episodios de ≥ 1 día · total {stats['total'] / 1e6:+.2f}M · "
          f"ganancia de las patas ganadoras {stats['ganancia'] / 1e6:+.2f}M · pérdida de las perdedoras {stats['perdida'] / 1e6:+.2f}M")
    print(f"La pata más grande era la que ganó en {stats['gana_mas_grande']} de {stats['n']} · "
          f"la perdedora terminó reducida (< 60 % de su máximo) en {stats['perdedora_reducida']} de {stats['n']}")


if __name__ == "__main__":
    main()
