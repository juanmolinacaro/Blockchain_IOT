"""¿Aciertan los avisos de la escucha? Mide cada aviso de `hft_eventos.jsonl` con el precio posterior.

Para cada aviso se mira el precio (velas de 1 minuto de Hyperliquid) 15 y 60 minutos después:

* **empuje** (💰 las cuentas que ganan / 🤖 los cazadores COMPRAN o VENDEN): acierta si el precio va en la
  dirección del empuje;
* **retiro** de un solo lado (🏦 retiran compras → camino libre abajo; retiran ventas → arriba): acierta
  si el precio va hacia el lado vaciado;
* **retiro de los dos lados a la vez**: no dice dirección. Se mide si después hay más movimiento que lo
  normal (la media del movimiento de 15 minutos en todo el periodo);
* **💥 liquidaciones de Binance**: se mide si el barrido sigue (continuación) o rebota.

Un caso no es una señal: el informe dice cuántos avisos de cada tipo hay y el acierto con su número.
"""
from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

COT = timezone(timedelta(hours=-5))
HORIZONS = (15, 60)
PAIR_S = 10          # retiros de compras y ventas a menos de 10 s: "los dos lados"


@dataclass
class Medida:
    t: int
    moneda: str
    clase: str            # empuje-ganadoras, empuje-cazadores, retiro-un-lado, retiro-ambos, liq-binance
    esperado: int         # +1 sube, −1 baja, 0 sin dirección
    precio: float
    cambios: dict         # minutos -> cambio relativo
    titulo: str
    ficha: dict | None = None      # operación armada en el aviso
    resultado_r: float | None = None   # +R si tocó TP1 antes que el stop, −1 si tocó el stop; None si ninguno

    def acierto(self, h: int) -> bool | None:
        c = self.cambios.get(h)
        if c is None or self.esperado == 0:
            return None
        return c * self.esperado > 0


def load_events(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return sorted(out, key=lambda e: e["t"])


def classify(events: list[dict]) -> list[tuple[dict, str, int]]:
    """(evento, clase, dirección esperada). Junta los retiros de compras y ventas simultáneos."""
    out = []
    retiros = [e for e in events if e["tipo"].startswith("retiro-")]
    used: set[int] = set()
    for e in events:
        tipo = e["tipo"]
        if tipo.startswith("empuje-"):
            grupo = "ganadoras" if e.get("grupo") == "ganadoras" or "ganan" in e.get("titulo", "") else "cazadores"
            if grupo == "ganadoras" and ("abren_usd" in e or "cierran_usd" in e):     # desde el 9 nov
                grupo += "-abren" if e.get("abren_usd", 0) >= e.get("cierran_usd", 0) else "-cierran"
            out.append((e, f"empuje-{grupo}", 1 if tipo.endswith("COMPRAN") else -1))
        elif tipo.startswith("ruptura-"):
            sub = "" if "confirmada" not in e else ("-confirmada" if e["confirmada"] else "-sin-confirmar")
            out.append((e, "ruptura" + sub, -1 if tipo.endswith("short") else 1))
        elif tipo.startswith("liq-binance-"):
            out.append((e, "liq-binance", -1 if tipo.endswith("largos") else 1))     # dirección del barrido
        elif tipo.startswith("retiro-") and id(e) not in used:
            twin = next((o for o in retiros if o is not e and id(o) not in used and o["moneda"] == e["moneda"]
                         and o["lado"] != e["lado"] and abs(o["t"] - e["t"]) <= PAIR_S * 1000), None)
            if twin is not None:
                used.update({id(e), id(twin)})
                out.append((e, "retiro-ambos", 0))
            else:
                used.add(id(e))
                out.append((e, "retiro-un-lado", -1 if e["lado"] == "compras" else 1))
    return out


def simulate_card(card: dict, candles: list, t_ms: int, max_hours: int = 24) -> float | None:
    """Resultado de la ficha en R: +r si toca TP1 antes que el stop, −1 si toca el stop (si en la misma vela
    se tocan los dos, se cuenta el stop, lo prudente). None si no toca ninguno en `max_hours`."""
    long = card["lado"] == "long"
    end = t_ms + max_hours * 3_600_000
    for k in candles:
        if k.t + 60_000 <= t_ms or k.t > end:
            continue
        hit_stop = k.l <= card["stop"] if long else k.h >= card["stop"]
        hit_tp = k.h >= card["tp1"] if long else k.l <= card["tp1"]
        if hit_stop:
            return -1.0
        if hit_tp:
            return float(card["r"])
    return None


def price_after(times: list[int], closes: list[float], t_ms: int, minutes: int) -> float | None:
    target = t_ms + minutes * 60_000
    i = bisect_right(times, target) - 1
    if i < 0 or target - times[i] > 2 * 60_000:
        return None
    return closes[i]


def measure(events: list[dict], candles: dict[str, list]) -> list[Medida]:
    """`candles`: moneda -> velas de 1 m (con .t inicio en ms y .c cierre)."""
    series = {c: ([k.t + 60_000 for k in cs], [k.c for k in cs]) for c, cs in candles.items()}   # hora de cierre
    out = []
    for e, clase, esperado in classify(events):
        times, closes = series.get(e["moneda"], ([], []))
        base = price_after(times, closes, e["t"], 0) or e["precio"]
        cambios = {}
        for h in HORIZONS:
            p = price_after(times, closes, e["t"], h)
            if p is not None and base:
                cambios[h] = p / base - 1
        card = e.get("ficha")
        res = simulate_card(card, candles.get(e["moneda"], []), e["t"]) if card else None
        out.append(Medida(e["t"], e["moneda"], clase, esperado, base, cambios, e.get("titulo", ""), card, res))
    return out


def typical_move(candles: list, minutes: int = 15) -> float:
    """Movimiento absoluto medio en `minutes` minutos (referencia para los retiros de los dos lados)."""
    closes = [k.c for k in candles]
    moves = [abs(closes[i + minutes] / closes[i] - 1) for i in range(0, len(closes) - minutes, minutes)]
    return sum(moves) / len(moves) if moves else 0.0


NAMES = {"empuje-ganadoras": "💰 empuje de las cuentas que ganan",
         "empuje-ganadoras-abren": "💰 las que ganan ABREN posición",
         "empuje-ganadoras-cierran": "💰 las que ganan solo CIERRAN",
         "empuje-cazadores": "🤖 empuje de los cazadores",
         "retiro-un-lado": "🏦 retiro de un solo lado", "retiro-ambos": "🏦 retiro de los dos lados a la vez",
         "liq-binance": "💥 liquidaciones de Binance (¿sigue el barrido?)",
         "ruptura": "📉📈 ruptura de compresión a favor de la tendencia",
         "ruptura-confirmada": "📉📈 ruptura CONFIRMADA por los datos",
         "ruptura-sin-confirmar": "📉📈 ruptura SIN confirmar"}


def report(medidas: list[Medida], typical: dict[str, float]) -> list[str]:
    lines = [f"{'aviso (hora Colombia)':51}  {'precio':>9}  {'15 min':>8}  {'60 min':>8}  acierto 15/60"]
    for m in medidas:
        when = datetime.fromtimestamp(m.t / 1000, COT).strftime("%a %d %H:%M")
        c15, c60 = (m.cambios.get(h) for h in HORIZONS)
        f = lambda c: "     —" if c is None else f"{c * 100:+7.2f}%"
        hit = lambda h: {True: "sí", False: "no", None: "—"}[m.acierto(h)]
        lines.append(f"{when} {m.moneda:3} {NAMES[m.clase][:34]:34}  {m.precio:>9,.1f}  {f(c15):>8}  {f(c60):>8}  "
                     f"{hit(15)}/{hit(60)}")
    lines.append("")
    for clase, name in NAMES.items():
        ms = [m for m in medidas if m.clase == clase]
        if not ms:
            continue
        if clase == "retiro-ambos":
            big = [m for m in ms if m.cambios.get(15) is not None
                   and abs(m.cambios[15]) > 1.5 * typical.get(m.moneda, 1)]
            done = [m for m in ms if m.cambios.get(15) is not None]
            normal = ", ".join(f"{c} {v * 100:.2f} %" for c, v in sorted(typical.items()))
            lines.append(f"{name}: {len(ms)} avisos · {len(big)} de {len(done)} con movimiento > 1,5× lo normal "
                         f"en 15 min (lo normal: {normal})")
            continue
        parts = []
        for h in HORIZONS:
            done = [m for m in ms if m.acierto(h) is not None]
            ok = sum(m.acierto(h) for m in done)
            parts.append(f"{h} min {ok}/{len(done)}" + (f" ({ok / len(done) * 100:.0f} %)" if done else ""))
        lines.append(f"{name}: {len(ms)} avisos · acierto " + " · ".join(parts))
    cards = [m for m in medidas if m.ficha]
    if cards:
        done = [m for m in cards if m.resultado_r is not None]
        total = sum(m.resultado_r for m in done)
        lines.append(f"📋 Fichas de operación: {len(cards)} · cerradas {len(done)} · ganadoras "
                     f"{sum(m.resultado_r > 0 for m in done)} · resultado {total:+.2f}R")
    lines.append("Pocos casos todavía: con menos de ~20 avisos de un tipo, el porcentaje no es fiable.")
    return lines


# ---------------------------------------------------------------- revisión diaria (escucha)
MEASURED = Path("data/avisos_medidos.jsonl")
SHORT = {"empuje-ganadoras": "💰", "empuje-ganadoras-abren": "💰abren", "empuje-ganadoras-cierran": "💰cierran",
         "empuje-cazadores": "🤖", "retiro-un-lado": "🏦1lado", "retiro-ambos": "🏦2lados", "liq-binance": "💥",
         "ruptura": "📉📈ruptura", "ruptura-confirmada": "✅ruptura", "ruptura-sin-confirmar": "⚠ruptura"}


def _record(m: Medida) -> dict:
    return {"t": m.t, "moneda": m.moneda, "clase": m.clase, "esperado": m.esperado,
            "cambios": {str(k): round(v, 5) for k, v in m.cambios.items()},
            "acierto_15": m.acierto(15), "acierto_60": m.acierto(60), "ficha": m.ficha, "r": m.resultado_r}


def update_measured(events: list[dict], candles: dict[str, list], now_ms: int, path: Path = MEASURED) -> list[dict]:
    """Guarda (una sola vez) cada aviso ya medido: con los 60 min cumplidos y, si traía ficha, con la ficha
    resuelta o con más de 24 h. Devuelve todos los medidos (los de días anteriores incluidos)."""
    done = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                done.append(json.loads(line))
            except ValueError:
                continue
    seen = {(d["t"], d["moneda"], d["clase"]) for d in done}
    new = []
    for m in measure(events, candles):
        if (m.t, m.moneda, m.clase) in seen or 60 not in m.cambios:
            continue
        if m.ficha and m.resultado_r is None and now_ms - m.t < 24 * 3_600_000:
            continue
        new.append(_record(m))
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for d in new:
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    return done + new


def summary_lines(records: list[dict], since_ms: int = 0) -> list[str]:
    rs = [d for d in records if d["t"] >= since_ms]
    out = []
    for clase, short in SHORT.items():
        cs = [d for d in rs if d["clase"] == clase]
        if not cs:
            continue
        if clase == "retiro-ambos":
            out.append(f"{short} {len(cs)}")
            continue
        ok = [d for d in cs if d["acierto_60"] is not None]
        out.append(f"{short} {sum(d['acierto_60'] for d in ok)}/{len(ok)}")
    cards = [d for d in rs if d.get("ficha") and d.get("r") is not None]
    if cards:
        out.append(f"📋 fichas {sum(d['r'] for d in cards):+.1f}R ({sum(d['r'] > 0 for d in cards)}/{len(cards)})")
    return out


def daily_review(source, events_path: Path, winners_now: set[str], winners_before: set[str],
                 now_ms: int | None = None) -> str:
    """Texto corto para el móvil: aciertos (a 60 min) de los avisos de hoy y del acumulado, resultado de
    las fichas en R y cambios en las cuentas que ganan. Así se ajusta cada día, sin esperar al mes."""
    import time as _t
    now_ms = now_ms or int(_t.time() * 1000)
    events = load_events(events_path) if events_path.exists() else []
    start = max(now_ms - 3 * 86_400_000, (events[0]["t"] - 30 * 60_000) if events else now_ms)
    recent = [e for e in events if e["t"] >= start]
    coins = sorted({e["moneda"] for e in recent})
    candles = {c: source.candles(c, "1m", start, now_ms) for c in coins}
    records = update_measured(recent, candles, now_ms)
    day0 = int(datetime.fromtimestamp(now_ms / 1000, COT).replace(hour=0, minute=0, second=0,
                                                                     microsecond=0).timestamp() * 1000)
    today = summary_lines(records, day0)
    total = summary_lines(records)
    lines = [f"Hoy (acierto a 60 min): {' · '.join(today) if today else 'sin avisos medidos'}",
             f"Acumulado: {' · '.join(total) if total else '—'}"]
    entered, left = winners_now - winners_before, winners_before - winners_now
    w = f"Cuentas que ganan: {len(winners_now)}"
    if entered:
        w += " · entran " + ", ".join(a[:6] for a in sorted(entered))
    if left:
        w += " · salen " + ", ".join(a[:6] for a in sorted(left))
    lines.append(w)
    lines.append("Formato: aciertos/medidos. Pocos casos = no fiable todavía.")
    return "\n".join(lines)
