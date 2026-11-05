"""Datos públicos de Binance Futuros para la escucha (corre en el computador de Juan).

Binance no dice quién es quién ni dónde se liquida cada posición (Hyperliquid sí), pero publica datos
agregados que completan el cuadro. Cada minuto, para BTC y ETH, se guarda en
`data/binance_minuto.csv`:

* volumen y **volumen agresivo de compra / venta** (vela de 1 minuto),
* **interés abierto** (contratos abiertos) y **funding**,
* **liquidaciones** reales que ocurrieron en ese minuto (canal en vivo `forceOrder`), de largos y de
  cortos. Binance envía como mucho una por segundo y moneda, así que es un mínimo, no el total,
* proporción largos/cortos de los **top traders** (por posición) y de **todas las cuentas** (cada 5 min).

Aviso al móvil cuando en un minuto se liquida mucho de un lado (barrido confirmado).
Desde los servidores de la nube Binance está bloqueado; desde Colombia funciona.
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("escucha")
FAPI = "https://fapi.binance.com"
WS = "wss://fstream.binance.com/stream?streams=btcusdt@forceOrder/ethusdt@forceOrder"
SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
CSV_PATH = Path("data/binance_minuto.csv")
COT = timezone(timedelta(hours=-5))
LIQ_ALERT_USD = {"BTC": 5_000_000, "ETH": 2_000_000}      # liquidado en 1 minuto para avisar
HEADER = ["hora_col", "moneda", "precio", "volumen_usd", "compra_agresiva_usd", "venta_agresiva_usd",
          "interes_abierto", "funding", "liq_largos_usd", "liq_cortos_usd", "top_traders_largos_cortos",
          "cuentas_largos_cortos"]


def parse_force_order(msg: dict) -> tuple[str, str, float] | None:
    """(moneda, 'largos' | 'cortos', USD). Una orden de VENTA forzada liquida a un largo."""
    o = (msg.get("data") or msg).get("o")
    if not o:
        return None
    coin = next((c for c, s in SYMBOLS.items() if s == o.get("s")), None)
    if not coin:
        return None
    qty = float(o.get("z") or o.get("q") or 0)
    px = float(o.get("ap") or o.get("p") or 0)
    return coin, ("largos" if o.get("S") == "SELL" else "cortos"), qty * px


def build_row(coin: str, ts: str, kline: list, oi: dict, premium: dict, liq: dict, ratios: dict) -> list:
    """Fila del CSV a partir de las respuestas de la API (kline = vela de 1 m ya cerrada)."""
    quote_vol = float(kline[7])
    taker_buy = float(kline[10])
    return [ts, coin, float(kline[4]), round(quote_vol), round(taker_buy), round(quote_vol - taker_buy),
            float(oi.get("openInterest", 0) or 0), float(premium.get("lastFundingRate", 0) or 0),
            round(liq.get("largos", 0.0)), round(liq.get("cortos", 0.0)),
            ratios.get("top", ""), ratios.get("cuentas", "")]


class BinanceState:
    def __init__(self):
        self.liq: dict[str, dict[str, float]] = {}       # moneda -> {largos, cortos} del minuto en curso
        self.ratios: dict[str, dict] = {}
        self.pending: list[list] = []
        self.last_ratio = 0.0
        self.available = True
        self.recent: dict[str, list] = {c: [] for c in SYMBOLS}   # últimas filas por moneda (para el resumen)

    def add_liq(self, coin: str, side: str, usd: float) -> None:
        d = self.liq.setdefault(coin, {"largos": 0.0, "cortos": 0.0})
        d[side] += usd

    def summary(self, minutes: int = 15) -> str:
        parts = []
        for coin, rows in self.recent.items():
            rows = rows[-minutes:]
            if not rows:
                continue
            ll = sum(r[8] for r in rows)
            lc = sum(r[9] for r in rows)
            buy = sum(r[4] for r in rows)
            sell = sum(r[5] for r in rows)
            parts.append(f"{coin} OI {rows[-1][6]:,.0f} · agresivo {buy / 1e6:.0f}M compra / {sell / 1e6:.0f}M venta"
                         f" · liquidado largos ${ll / 1e6:.1f}M / cortos ${lc / 1e6:.1f}M")
        return "Binance: " + " | ".join(parts) if parts else "Binance: sin datos todavía"


def _get(session, path: str, **params):
    r = session.get(FAPI + path, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def poll_minute(bstate: BinanceState, session, liq: dict | None = None) -> list[list]:
    ts = (datetime.now(COT) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
    now = time.time()
    if now - bstate.last_ratio >= 300:                     # las proporciones salen cada 5 minutos
        bstate.last_ratio = now
        for coin, sym in SYMBOLS.items():
            try:
                top = _get(session, "/futures/data/topLongShortPositionRatio", symbol=sym, period="5m", limit=1)
                acc = _get(session, "/futures/data/globalLongShortAccountRatio", symbol=sym, period="5m", limit=1)
                bstate.ratios[coin] = {"top": float(top[-1]["longShortRatio"]) if top else "",
                                       "cuentas": float(acc[-1]["longShortRatio"]) if acc else ""}
            except Exception:
                pass
    rows = []
    for coin, sym in SYMBOLS.items():
        kl = _get(session, "/fapi/v1/klines", symbol=sym, interval="1m", limit=2)
        oi = _get(session, "/fapi/v1/openInterest", symbol=sym)
        prem = _get(session, "/fapi/v1/premiumIndex", symbol=sym)
        if liq is None:
            liq, bstate.liq = bstate.liq, {}
        row = build_row(coin, ts, kl[0], oi, prem, liq.get(coin, {}), bstate.ratios.get(coin, {}))
        rows.append(row)
        bstate.recent[coin] = (bstate.recent[coin] + [row])[-120:]
    return rows


def flush(bstate: BinanceState) -> None:
    if not bstate.pending:
        return
    try:
        new = not CSV_PATH.exists()
        CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CSV_PATH.open("a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(HEADER)
            w.writerows(bstate.pending)
        bstate.pending = []
    except PermissionError:
        log.warning("El archivo %s está abierto; guardo los datos de Binance en memoria.", CSV_PATH)


async def _minute(bstate: BinanceState, session, liq: dict, alert, first: bool) -> None:
    """Datos del minuto en segundo plano (la conexión de liquidaciones sigue leyendo mientras tanto)."""
    try:
        rows = await asyncio.to_thread(poll_minute, bstate, session, liq)
    except Exception as exc:
        log.error("Binance (datos del minuto): %s", exc)
        return
    bstate.pending += rows
    await asyncio.to_thread(flush, bstate)
    if first:
        log.warning("Binance datos ✓ " + " | ".join(f"{r[1]} {r[2]:,.0f} · interés abierto {r[6]:,.0f}" for r in rows))
    for r in rows:
        coin, px = r[1], r[2]
        for side, usd in (("largos", r[8]), ("cortos", r[9])):
            if usd >= LIQ_ALERT_USD.get(coin, 5e6):
                alert(f"liq-binance-{coin}-{side}", f"💥 {coin}: Binance liquidó {side} ${usd / 1e6:.1f}M en 1 minuto",
                      f"Barrido en marcha a {px:,.0f} (mínimo registrado; Binance publica una liquidación por "
                      f"segundo)", {"moneda": coin, "precio": px, "usd": usd, "lado": side})


async def run(alert, should_stop, bstate: BinanceState) -> None:
    """Escucha liquidaciones en vivo y, cada minuto, consulta los datos agregados.
    `alert(clave, título, texto, datos)` es el aviso de la escucha principal (mismo enfriamiento)."""
    import requests
    import websockets

    session = requests.Session()
    last_minute = int(time.time() // 60)
    failures = 0
    jobs: set = set()
    while not should_stop():
        try:
            async with websockets.connect(WS, ping_interval=20, ping_timeout=60, max_size=None,
                                          max_queue=1024) as ws:
                log.warning("Binance conectado ✓ (liquidaciones en vivo); los datos por minuto llegan en 1-2 min")
                bstate.available, failures = True, 0
                first_data = True
                while not should_stop():
                    try:
                        parsed = parse_force_order(json.loads(await asyncio.wait_for(ws.recv(), timeout=5)))
                        if parsed:
                            bstate.add_liq(*parsed)
                    except asyncio.TimeoutError:
                        pass
                    if int(time.time() // 60) != last_minute:
                        last_minute = int(time.time() // 60)
                        snap, bstate.liq = bstate.liq, {}
                        task = asyncio.create_task(_minute(bstate, session, snap, alert, first_data))
                        jobs.add(task)
                        task.add_done_callback(jobs.discard)
                        first_data = False
        except Exception as exc:
            failures += 1
            if bstate.available or failures in (1, 10):
                log.error("Binance no disponible (%s: %s); reintento cada minuto", type(exc).__name__, exc)
            bstate.available = False
            await asyncio.sleep(60 if failures < 10 else 300)
