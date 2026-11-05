"""Radar de alta frecuencia: encontrar y clasificar las cuentas de Hyperliquid que operan como robots.

Pregunta de Juan (5 nov 2026): los que ganan con cada barrido de stops y pools son los robots de alta
frecuencia; ¿cómo detectarlos? En Hyperliquid todo es público:

* el ranking da el volumen y el PnL de cada cuenta (día / semana / mes);
* los fills de cada cuenta dicen si fue *maker* (dejó la orden en el libro) o *taker* (cruzó el
  precio, `crossed`), el tamaño y la hora;
* las órdenes abiertas de cada cuenta están a la vista;
* cada operación pública trae las dos direcciones (comprador y vendedor).

Tipos que se distinguen:
* **Cazador**: mayoría taker, cientos o miles de fills por hora, tamaños pequeños. Empuja el precio.
* **Creador de mercado**: mayoría maker y muchas órdenes abiertas. Pone la liquidez (y la retira).
* **Ejecutor**: tamaño fijo y ritmo regular (TWAP de una ballena, troceando una orden grande).
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass

WEEK_VOLUME_MIN = 1e9          # >= $1.000M de volumen semanal
TURNOVER_MIN = 50              # o volumen semanal >= 50 veces el tamaño de la cuenta


@dataclass
class HFTProfile:
    address: str
    week_volume: float
    week_pnl: float
    account_value: float
    fills_per_hour: float
    maker_share: float
    median_usd: float
    size_cv: float             # dispersión del tamaño (0 = siempre igual: típico de un ejecutor)
    open_orders: int
    top_coins: list
    kind: str = ""

    def classify(self) -> str:
        if self.size_cv < 0.15 and self.fills_per_hour < 500:
            self.kind = "ejecutor"
        elif self.maker_share >= 0.7:
            self.kind = "creador de mercado"
        elif self.maker_share <= 0.35:
            self.kind = "cazador"
        else:
            self.kind = "mixto"
        return self.kind


def candidates(leaderboard_rows: list[dict], top: int = 25) -> list[dict]:
    """Cuentas con volumen semanal enorme o rotación muy alta respecto a su capital."""
    out = []
    for r in leaderboard_rows:
        w = dict(r["windowPerformances"])["week"]
        vol, acct = float(w["vlm"]), float(r["accountValue"])
        if vol >= WEEK_VOLUME_MIN or (acct > 1e6 and vol / acct >= TURNOVER_MIN):
            out.append({"address": r["ethAddress"], "week_volume": vol, "week_pnl": float(w["pnl"]),
                        "account_value": acct})
    return sorted(out, key=lambda c: -c["week_volume"])[:top]


def profile(source, cand: dict) -> HFTProfile | None:
    fills = source._info({"type": "userFills", "user": cand["address"]}) or []     # las ~2.000 más recientes
    if len(fills) < 20:
        return None
    ts = [int(f["time"]) for f in fills]
    span_h = max((max(ts) - min(ts)) / 3.6e6, 1 / 60)
    usd = [float(f["sz"]) * float(f["px"]) for f in fills]
    counts: dict[str, int] = {}
    for f in fills:
        counts[f["coin"]] = counts.get(f["coin"], 0) + 1
    try:
        oo = len(source._info({"type": "openOrders", "user": cand["address"]}) or [])
    except Exception:
        oo = -1
    p = HFTProfile(cand["address"], cand["week_volume"], cand["week_pnl"], cand["account_value"],
                   len(fills) / span_h, sum(1 for f in fills if not f.get("crossed")) / len(fills),
                   statistics.median(usd), statistics.pstdev(usd) / (statistics.fmean(usd) or 1), oo,
                   [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:3]])
    p.classify()
    return p


def scan(source, top: int = 25, pause_s: float = 0.3) -> list[HFTProfile]:
    rows = source._request("GET", source.leaderboard_url)["leaderboardRows"]
    out = []
    for c in candidates(rows, top):
        try:
            p = profile(source, c)
        except Exception:
            p = None
        if p:
            out.append(p)
        time.sleep(pause_s)
    return out


def taker_flow(trades: list[dict], hft: dict[str, str]) -> dict[str, dict[str, float]]:
    """Flujo agresivo (taker) por tipo de robot en una lista de operaciones públicas.

    En cada operación `users` = [comprador, vendedor] y `side` = lado del taker ("B" compra, "A" vende).
    Devuelve {tipo: {"compra": USD, "venta": USD}} solo para las cuentas del radar.
    """
    out: dict[str, dict[str, float]] = {}
    for t in trades:
        buyer, seller = t["users"]
        taker = buyer if t["side"] == "B" else seller
        kind = hft.get(taker)
        if not kind:
            continue
        d = out.setdefault(kind, {"compra": 0.0, "venta": 0.0})
        d["compra" if t["side"] == "B" else "venta"] += float(t["sz"]) * float(t["px"])
    return out


def as_dict(p: HFTProfile) -> dict:
    return asdict(p)
