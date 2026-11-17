"""¿Cómo nos habría ido operando esta semana con las señales que ya tenemos? (14 nov 2026)

Repite, vela de 1H por vela de 1H, el semáforo (M/W, trampa, compresión) sobre BTC y ETH del domingo 8 al
sábado 14 de noviembre, con la tendencia de cada momento (EMA 50 diaria) y el voto de la mayoría de Binance
(datos del PC). Gestión del semáforo: mitad a 1R y stop a la entrada, resto a 2R, 48 h, comisión 0,09 %.
Dentro de la vela no se sabe qué tocó primero: si una vela toca stop y objetivo, se cuenta el stop (pesimista).
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copytrading import semaforo as sm                      # noqa: E402
from copytrading.method.monitor import trend_state, trading_allowed   # noqa: E402
from copytrading.sources.hyperliquid import HyperliquidSource         # noqa: E402

COT = timezone(timedelta(hours=-5))
START = datetime(2026, 11, 8, 0, 0, tzinfo=COT)
BIN = Path("data/escucha_pc/2026-11-14/binance_minuto.csv")


def mayoria(coin: str) -> dict[str, int]:
    """Voto de la mayoría por hora: −1 si L/S ≥ 2 con funding > 0, +1 si L/S ≤ 0,8 con funding < 0."""
    out = {}
    if not BIN.exists():
        return out
    with BIN.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["moneda"] != coin:
                continue
            try:
                ls, f = float(r["cuentas_largos_cortos"]), float(r["funding"])
            except ValueError:
                continue
            out[r["hora_col"][:13]] = -1 if ls >= 2 and f > 0 else 1 if 0 < ls <= 0.8 and f < 0 else 0
    return out


def run(coin: str, src) -> list[tuple]:
    now = int(time.time() * 1000)
    c1 = [c for c in src.candles(coin, "1h", int(START.timestamp() * 1000) - 420 * 3_600_000, now) if c.t + 3_600_000 <= now]
    c4 = src.candles(coin, "4h", int(START.timestamp() * 1000) - 830 * 86_400_000, now)
    may = mayoria(coin)
    items: list[sm.Paper] = []
    rows = []
    first = next(i for i, c in enumerate(c1) if c.t >= START.timestamp() * 1000)
    for i in range(first, len(c1)):
        t_close = c1[i].t + 3_600_000
        for p in items:                                 # avanza lo abierto con esta vela
            if p.status in ("pendiente", "abierta") and p.created < t_close - 1:
                sm.update(p, c1[i].h, c1[i].l, t_close)
        trend = trend_state([k for k in c4 if k.t + 4 * 3_600_000 <= t_close])[0]
        hour = datetime.fromtimestamp(c1[i].t / 1000, COT).strftime("%Y-%m-%d %H")
        for s in sm.detect_all(c1[:i + 1], trend):
            sign = -1 if s.side == "short" else 1
            con_tendencia = (trend == "BAJISTA") == (s.side == "short")
            m = may.get(hour, 0)
            ok = con_tendencia and m * sign >= 0 and trading_allowed(t_close)
            p = sm.open_signal(items, s, coin, t_close, ok, {"tendencia": 1 if con_tendencia else -1, "mayoría": m})
            if p:
                rows.append(p)
    return rows


def main() -> None:
    src = HyperliquidSource()
    allp = []
    for coin in ("BTC", "ETH"):
        allp += run(coin, src)
    for p in sorted(allp, key=lambda p: p.created):
        t = datetime.fromtimestamp(p.created / 1000, COT).strftime("%a %d %H:%M")
        print(f"{t} {p.coin} {p.setup:11} {p.side:5} {'🚦 pasa' if p.filtro else '  no  '} entrada {p.entry:9,.1f} "
              f"stop {p.stop:9,.1f} → {p.status:10} {p.r:+.2f}R {p.exit_reason}  [{p.note}]")
    print()
    print("\n".join(sm.scoreboard(allp)))


if __name__ == "__main__":
    main()
