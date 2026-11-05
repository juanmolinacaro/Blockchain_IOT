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

Afinado (5 nov 2026): una cuenta solo se etiqueta si cumple TODAS las señales (rotación ≥ 20x su
capital, compra y venta equilibradas, vuelve a quedar sin posición en ≤ 2 h, sin TWAP, y fills que
cuadran con su volumen semanal); además, el creador de mercado debe usar órdenes pequeñas y el
cazador rotar ≥ 50x. Si falla una sola, queda "sin confirmar": se prefiere no etiquetar a etiquetar mal.
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
    # afinado (5 nov 2026)
    turnover: float = 0.0          # volumen semanal / capital
    net_ratio: float = 0.0         # |compras - ventas| / total: 0 = equilibrado, 1 = todo en un sentido
    round_trip_h: float = -1.0     # horas medianas entre momentos "sin posición" (ida y vuelta)
    fills_per_order: float = 0.0   # 1-2 = órdenes pequeñas; muchas = una orden grande barriendo el libro
    twap_share: float = 0.0        # fracción de fills de TWAP nativo de Hyperliquid (ejecutor seguro)
    cloid_share: float = 0.0       # fracción con id de cliente (típico de bots)
    order_churn: float = -1.0      # órdenes abiertas que cambian en 15 s (cotizador que reemplaza órdenes)
    mean_usd: float = 0.0          # tamaño medio por fill
    checks: dict = None            # señales que cumple
    confidence: str = ""

    def classify(self) -> str:
        """Etiqueta solo cuando TODAS las señales clave coinciden; si no, 'sin confirmar'.
        Así se prefiere no etiquetar antes que etiquetar mal."""
        fast_rt = 0 <= self.round_trip_h <= 2
        # coherencia: los fills vistos deben cuadrar con el volumen semanal (si no, faltan datos de la cuenta)
        expected_per_h = self.week_volume / max(self.mean_usd or self.median_usd, 1.0) / 168
        coherent = expected_per_h > 0 and 0.1 <= self.fills_per_hour / expected_per_h <= 10
        c = {
            "datos coherentes con su volumen": coherent,
            "rotación alta (≥ 20x el capital)": self.turnover >= 20,
            "equilibrado (compra ≈ vende)": self.net_ratio <= 0.35,
            "vuelve a cero en ≤ 2 h": fast_rt,
            "sin TWAP": self.twap_share < 0.05,
        }
        small_orders = self.fills_per_order <= 3          # un creador de mercado pone órdenes pequeñas
        maker_ok = self.maker_share >= 0.7
        taker_ok = self.maker_share <= 0.35 and self.fills_per_hour >= 100 and self.median_usd <= 5000
        quoting = self.open_orders >= 10 or self.order_churn >= 0.2
        self.checks = c
        if self.twap_share >= 0.5 or (self.net_ratio >= 0.7 and (self.size_cv < 0.3 or self.fills_per_order > 3)):
            self.kind, self.confidence = "ejecutor", "alta" if self.twap_share >= 0.5 else "media"
        elif all(c.values()) and maker_ok and small_orders:
            self.kind = "creador de mercado"
            self.confidence = "alta" if quoting else "media"
        elif all(c.values()) and taker_ok and self.turnover >= 50:
            self.kind, self.confidence = "cazador", "alta"
        else:
            self.kind, self.confidence = "sin confirmar", ""
        return self.kind


def _round_trip_hours(fills: list[dict]) -> float:
    """Mediana de horas entre momentos en que la cuenta queda (casi) sin posición, por moneda."""
    gaps = []
    by_coin: dict[str, list[dict]] = {}
    for f in fills:
        by_coin.setdefault(f["coin"], []).append(f)
    for fs in by_coin.values():
        fs.sort(key=lambda f: int(f["time"]))
        pos = [float(f["startPosition"]) + (float(f["sz"]) if f["side"] == "B" else -float(f["sz"])) for f in fs]
        peak = max(abs(p) for p in pos) or 1.0
        flats = [int(f["time"]) for f, p in zip(fs, pos) if abs(p) <= 0.1 * peak]
        gaps += [(b - a) / 3.6e6 for a, b in zip(flats, flats[1:]) if b > a]
    return statistics.median(gaps) if gaps else -1.0


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


def profile(source, cand: dict, churn_wait_s: float = 15) -> HFTProfile | None:
    fills = source._info({"type": "userFills", "user": cand["address"]}) or []     # las ~2.000 más recientes
    if len(fills) < 20:
        return None
    ts = [int(f["time"]) for f in fills]
    span_h = max((max(ts) - min(ts)) / 3.6e6, 1 / 60)
    usd = [float(f["sz"]) * float(f["px"]) for f in fills]
    buys = sum(u for u, f in zip(usd, fills) if f["side"] == "B")
    sells = sum(usd) - buys
    counts: dict[str, int] = {}
    for f in fills:
        counts[f["coin"]] = counts.get(f["coin"], 0) + 1
    oids = {f.get("oid") for f in fills}

    def open_ids():
        try:
            return {o["oid"] for o in (source._info({"type": "openOrders", "user": cand["address"]}) or [])}
        except Exception:
            return None
    first = open_ids()
    churn = -1.0
    if first and len(first) >= 10 and churn_wait_s:
        time.sleep(churn_wait_s)
        second = open_ids()
        if second is not None:
            churn = 1 - len(first & second) / len(first)
    p = HFTProfile(cand["address"], cand["week_volume"], cand["week_pnl"], cand["account_value"],
                   len(fills) / span_h, sum(1 for f in fills if not f.get("crossed")) / len(fills),
                   statistics.median(usd), statistics.pstdev(usd) / (statistics.fmean(usd) or 1),
                   len(first) if first is not None else -1,
                   [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:3]],
                   turnover=cand["week_volume"] / max(cand["account_value"], 1.0),
                   net_ratio=abs(buys - sells) / (buys + sells or 1),
                   round_trip_h=_round_trip_hours(fills),
                   fills_per_order=len(fills) / max(len(oids), 1),
                   twap_share=sum(1 for f in fills if f.get("twapId")) / len(fills),
                   cloid_share=sum(1 for f in fills if f.get("cloid")) / len(fills),
                   order_churn=churn, mean_usd=statistics.fmean(usd))
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
