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
# canal de TODAS las liquidaciones del mercado (se filtra BTC/ETH): así hay mensajes casi siempre y un
# silencio largo delata una conexión que no entrega datos. Si una dirección calla, se prueba la otra.
WS_URLS = ["wss://fstream.binance.com/market/stream?streams=!forceOrder@arr",
           "wss://fstream.binance.com/stream?streams=!forceOrder@arr"]
SILENCE_S = 15 * 60
SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
CSV_PATH = Path("data/binance_minuto.csv")
COT = timezone(timedelta(hours=-5))
LIQ_ALERT_USD = {"BTC": 5_000_000, "ETH": 2_000_000}      # liquidado en 1 minuto para avisar
HEADER = ["hora_col", "moneda", "precio", "volumen_usd", "compra_agresiva_usd", "venta_agresiva_usd",
          "interes_abierto", "funding", "liq_largos_usd", "liq_cortos_usd", "top_traders_largos_cortos",
          "cuentas_largos_cortos"]


def parse_force_order(msg: dict) -> tuple[str, str, float] | None:
    """(moneda, 'largos' | 'cortos', USD). Una orden de VENTA forzada liquida a un largo."""
    data = msg.get("data") or msg
    if isinstance(data, list):              # algunos formatos agrupan varias liquidaciones
        data = data[0] if data else {}
    o = data.get("o")
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
        self.liq_msgs = 0                                           # mensajes de liquidación recibidos (cualquier moneda)
        self.last_error = 0.0                                       # último error de los datos por minuto

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
        tail = f" | mensajes de liquidación recibidos: {self.liq_msgs:,}"
        return ("Binance: " + " | ".join(parts) if parts else "Binance: sin datos todavía") + tail


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
        closed = (int(time.time()) // 60 - 1) * 60_000          # la vela de 1 minuto que acaba de cerrar
        kl = _get(session, "/fapi/v1/klines", symbol=sym, interval="1m", startTime=closed, limit=1)
        if not kl or int(kl[0][0]) != closed:
            continue                                          # aún no publicada: mejor sin fila que repetida
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
        if time.time() - bstate.last_error >= 1800:          # no llenar la ventana: un aviso cada 30 min
            bstate.last_error = time.time()
            log.error("Binance (datos del minuto) no disponible: %s; sigo intentando cada minuto", exc)
        return
    if bstate.last_error:
        log.warning("Binance (datos del minuto) disponible de nuevo ✓")
        bstate.last_error = 0.0
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


async def _poll_loop(alert, should_stop, bstate: BinanceState, session) -> None:
    """Datos por minuto (REST): corre aparte de las liquidaciones en vivo, así un fallo del canal en vivo
    no deja el archivo sin filas (el 5 nov no hubo filas desde las 11:09 por eso)."""
    last_minute = int(time.time() // 60)
    first = True
    while not should_stop():
        await asyncio.sleep(1)
        if int(time.time() // 60) == last_minute:
            continue
        last_minute = int(time.time() // 60)
        await asyncio.sleep(3)                         # dar tiempo a que Binance publique la vela cerrada
        snap, bstate.liq = bstate.liq, {}
        before = len(bstate.recent.get("BTC", []))
        await _minute(bstate, session, snap, alert, first)
        if len(bstate.recent.get("BTC", [])) > before:
            first = False


async def _liquidations(should_stop, bstate: BinanceState) -> None:
    """Liquidaciones en vivo (websocket), con dirección alternativa si una calla."""
    import websockets

    failures = 0
    url_i = 0
    while not should_stop():
        url = WS_URLS[url_i % len(WS_URLS)]
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=60, max_size=None,
                                          max_queue=1024) as ws:
                log.warning("Binance conectado ✓ (liquidaciones en vivo, %s)", url.split("/")[3])
                bstate.available, failures = True, 0
                last_msg = time.time()
                while not should_stop():
                    try:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                        last_msg = time.time()
                        bstate.liq_msgs += 1
                        parsed = parse_force_order(msg)
                        if parsed:
                            bstate.add_liq(*parsed)
                    except asyncio.TimeoutError:
                        pass
                    if time.time() - last_msg > SILENCE_S:
                        log.warning("Binance: 15 min sin liquidaciones por %s; pruebo la otra dirección", url.split("/")[3])
                        url_i += 1
                        break
        except Exception as exc:
            failures += 1
            url_i += 1                                 # probar la otra dirección en el siguiente intento
            if bstate.available or failures in (1, 10):
                log.error("Binance liquidaciones en vivo no disponibles (%s: %s); reintento cada minuto",
                          type(exc).__name__, exc)
            bstate.available = False
            await asyncio.sleep(60 if failures < 10 else 300)


async def run(alert, should_stop, bstate: BinanceState) -> None:
    """Datos por minuto y liquidaciones en vivo, cada uno por su lado.
    `alert(clave, título, texto, datos)` es el aviso de la escucha principal (mismo enfriamiento)."""
    import requests

    session = requests.Session()
    await asyncio.gather(_poll_loop(alert, should_stop, bstate, session), _liquidations(should_stop, bstate))
