"""Pesos de los votos de la confirmación, medidos con los datos (13 nov 2026).

Juan: "no es lo que yo diga; es medir qué ventaja nos da la información". Cada voto de la confirmación se
reproduce sobre los datos por minuto de la escucha (muestra cada 15 min) y se mira si acertó la dirección
del precio 4 horas después. Su peso sale de ese acierto:

    peso = (acierto − 50 %) / 25 %, entre 0 y 2   → 50 % o menos = 0 (no vota); 75 % = 1; ≥ 100 % = 2

con al menos MIN_N casos; con menos, peso 1 (neutro) hasta tener datos. Los votos que se pueden reproducir
con los CSV: el empuje del público (en contra), las liquidaciones de largos (freno: alcista), el interés
abierto subiendo (combustible: bajista) y la mayoría sobreapalancada. Los demás (tendencia, ballenas,
imán) se miden con los avisos guardados que llevan sus votos. La escucha los recalcula cada noche y los
guarda en `data/pesos.json`.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

PESOS = Path("data/pesos.json")
HORIZON_MIN = 240
MIN_N = 30
CROWD_MIN = 2_000_000          # igual que la escucha (30 min)
LIQ_MIN = {"BTC": 5_000_000, "ETH": 2_000_000}   # largos liquidados en 60 min para votar "freno"
OI_MIN = 0.003                 # interés abierto +0,3 % en 60 min
CROWDED_LONG, CROWDED_SHORT = 2.0, 0.8
DEFAULT = 1.0


def weight(acc: float, n: int) -> float:
    if n < MIN_N:
        return DEFAULT
    return round(max(0.0, min(2.0, (acc - 0.5) / 0.25)), 2)


def _rows(path: Path, coin: str) -> dict[datetime, dict]:
    out: dict[datetime, dict] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("moneda") == coin and r.get("hora_col"):
                try:
                    out[datetime.strptime(r["hora_col"][:16], "%Y-%m-%d %H:%M")] = r
                except ValueError:
                    continue
    return out


def _f(r, k):
    try:
        return float(r.get(k) or 0) if r else 0.0
    except ValueError:
        return 0.0


def votes_from_csv(flow: dict, binance: dict, coin: str) -> list[tuple[dict, float]]:
    """(votos, cambio de precio a 4 h) cada 15 min, reproduciendo los votos que salen de los CSV."""
    px = {t: _f(r, "precio") for t, r in flow.items() if _f(r, "precio")}
    if not px:
        px = {t: _f(r, "precio") for t, r in binance.items() if _f(r, "precio")}
    times = sorted(px)
    out = []
    for t in times[::15]:
        fut = next((px[t + timedelta(minutes=HORIZON_MIN + d)] for d in range(3)
                    if t + timedelta(minutes=HORIZON_MIN + d) in px), None)
        if fut is None:
            continue
        v: dict[str, int] = {}
        crowd = sum(_f(flow.get(t - timedelta(minutes=m)), "otros_compra") - _f(flow.get(t - timedelta(minutes=m)), "otros_venta")
                    for m in range(30))
        if abs(crowd) >= CROWD_MIN:
            v["público"] = -1 if crowd > 0 else 1
        b0, b60 = binance.get(t), binance.get(t - timedelta(minutes=60))
        liq = sum(_f(binance.get(t - timedelta(minutes=m)), "liq_largos_usd") for m in range(60))
        if liq >= LIQ_MIN.get(coin, 5_000_000):
            v["liquidaciones"] = 1
        if b0 and b60 and _f(b60, "interes_abierto"):
            if _f(b0, "interes_abierto") / _f(b60, "interes_abierto") - 1 > OI_MIN:
                v["interés abierto"] = -1
        if b0:
            lc, fund = _f(b0, "cuentas_largos_cortos"), _f(b0, "funding")
            if lc >= CROWDED_LONG and fund > 0:
                v["mayoría"] = -1
            elif 0 < lc <= CROWDED_SHORT and fund < 0:
                v["mayoría"] = 1
        if v:
            out.append((v, fut / px[t] - 1))
    return out


def votes_from_events(events: list[dict], flow: dict, coin: str) -> list[tuple[dict, float]]:
    """Votos guardados en los avisos (tendencia, ballenas, imán…) con el precio 4 h después (del flujo)."""
    px = {t: _f(r, "precio") for t, r in flow.items() if _f(r, "precio")}
    out = []
    for e in events:
        if e.get("moneda") != coin or not e.get("votos"):
            continue
        # la escucha guarda hora_col en hora de Colombia; los avisos en ms UTC
        t = datetime.utcfromtimestamp(e["t"] / 1000) - timedelta(hours=5)
        t = t.replace(second=0, microsecond=0)
        p0 = next((px[t - timedelta(minutes=d)] for d in range(3) if t - timedelta(minutes=d) in px), None)
        p1 = next((px[t + timedelta(minutes=HORIZON_MIN + d)] for d in range(3)
                   if t + timedelta(minutes=HORIZON_MIN + d) in px), None)
        if p0 and p1:
            out.append(({k: v for k, v in e["votos"].items() if k in ("tendencia", "ballenas", "imán")}, p1 / p0 - 1))
    return out


def compute(flow_paths: list[Path], binance_paths: list[Path], events_path: Path | None, coins=("BTC", "ETH")) -> dict:
    tally: dict[str, list[int]] = {}
    for coin in coins:
        flow: dict = {}
        binance: dict = {}
        for p in flow_paths:
            flow.update(_rows(p, coin))
        for p in binance_paths:
            binance.update(_rows(p, coin))
        samples = votes_from_csv(flow, binance, coin)
        if events_path and events_path.exists():
            evs = []
            for line in events_path.read_text(encoding="utf-8").splitlines():
                try:
                    evs.append(json.loads(line))
                except ValueError:
                    continue
            samples += votes_from_events(evs, flow, coin)
        for votes, ch in samples:
            for k, v in votes.items():
                a = tally.setdefault(k, [0, 0])
                a[0] += int(v * ch > 0)
                a[1] += 1
    out = {}
    for k, (hit, n) in tally.items():
        acc = hit / n if n else 0.0
        out[k] = {"peso": weight(acc, n), "acierto": round(acc, 3), "n": n}
    return out


def save(weights: dict, path: Path = PESOS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "horizonte_min": HORIZON_MIN,
                                "votos": weights}, ensure_ascii=False, indent=1), encoding="utf-8")


def load(path: Path = PESOS) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: float(v["peso"]) for k, v in data.get("votos", {}).items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def report(weights: dict) -> list[str]:
    lines = [f"{'voto':18} {'acierto a 4 h':>14} {'casos':>6} {'peso':>5}"]
    for k, v in sorted(weights.items(), key=lambda kv: -kv[1]["peso"]):
        lines.append(f"{k:18} {v['acierto']:14.0%} {v['n']:6} {v['peso']:5.2f}"
                     + ("  (sin datos suficientes: neutro)" if v["n"] < MIN_N else "  (no vota)" if v["peso"] == 0 else ""))
    return lines
