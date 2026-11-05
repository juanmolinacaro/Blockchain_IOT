"""Escucha 24/7 de la alta frecuencia en Hyperliquid (programa independiente, sin Claude).

Pensado para dejarlo corriendo en el computador de Juan (Windows): `escuchar_hft.bat`.

Qué hace:
1. Carga el radar de robots (`data/alta_frecuencia.json`, se renueva solo cada 6 h).
2. Se conecta al canal en vivo de Hyperliquid y recibe cada operación de BTC y ETH. Cada operación
   trae las dos direcciones, así que se sabe si el agresor (taker) fue un robot cazador, un creador
   de mercado u otra cuenta.
3. Cada minuto guarda el flujo agresivo por tipo en `data/hft_flujo.csv`.
4. Cada minuto mira cuánta liquidez tienen puesta los creadores de mercado cerca del precio
   (sus órdenes abiertas a ±1 %) y la guarda en el mismo CSV.
5. Avisa al móvil (ntfy) cuando:
   * los cazadores empujan fuerte en una dirección (flujo neto de 5 min muy por encima de lo normal),
   * los creadores de mercado retiran gran parte de su liquidez de un lado del precio,
   * y dice si el precio va hacia un pool de liquidez de corto plazo (25-100x).
6. Guarda cada aviso en `data/hft_eventos.jsonl` para medir después si anticipan los barridos.

Es experimental: los umbrales son de partida y se ajustarán con los datos que se vayan guardando.
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import statistics
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("escucha")
WS_URL = "wss://api.hyperliquid.xyz/ws"
COINS = ("BTC", "ETH")
RADAR = Path("data/alta_frecuencia.json")
FLOW_CSV = Path("data/hft_flujo.csv")
EVENTS = Path("data/hft_eventos.jsonl")
COT = timezone(timedelta(hours=-5))
CONFIRMED = ("cazador", "creador de mercado")     # tipos confirmados por todas las señales del radar
COHORT = Path("data/hft_cohorte.json")            # las 30 cuentas que se estudian durante el mes
COHORT_SIZE = 30

# umbrales de partida
Z_PUSH = 3.0                 # flujo neto de 5 min de los cazadores: desviaciones sobre lo normal
MIN_PUSH_USD = 300_000       # ...y al menos este tamaño
PULL_RATIO = 0.4             # los creadores dejan < 40 % de su liquidez media de un lado
MIN_BOOK_USD = 200_000       # (solo si normalmente tenían al menos esto)
COOLDOWN_S = 30 * 60         # no repetir el mismo tipo de aviso antes de 30 min
BEAT_MIN = 15                # línea "✓ Funcionando" en la ventana cada 15 min
PHONE_BEAT_H = 6             # mensaje silencioso al móvil cada 6 h para saber que sigue viva


class State:
    def __init__(self, kinds: dict[str, str]):
        self.kinds = kinds                                       # dirección -> tipo
        self.minute: dict[str, dict[str, float]] = {}           # moneda -> acumulado del minuto
        self.price: dict[str, float] = {}
        self.net_hist: dict[str, deque] = {c: deque(maxlen=180) for c in COINS}      # flujo neto/min (3 h)
        self.book_hist: dict[str, deque] = {c: deque(maxlen=30) for c in COINS}     # (bid, ask) por minuto
        self.last_alert: dict[str, float] = {}
        self.zones: dict[str, tuple[list, list]] = {}
        self.trades_seen = 0
        self.trades_at_last_beat = 0
        self.alerts_since_beat = 0
        self.pending: list[list] = []                           # filas aún sin escribir (archivo bloqueado)
        self.hourly: dict[str, list] = {}       # cuenta -> [operaciones, USD, taker compra, taker venta, maker USD]
        self.hour_pending: list[list] = []
        self.warned_locked = False

    def add_trade(self, t: dict) -> None:
        coin = t["coin"]
        usd = float(t["sz"]) * float(t["px"])
        self.price[coin] = float(t["px"])
        buyer, seller = t.get("users", ["", ""])
        taker = (buyer if t["side"] == "B" else seller).lower()
        for who in {buyer.lower(), seller.lower()}:            # actividad de cada cuenta de la cohorte
            if who in self.kinds:
                h = self.hourly.setdefault(who, [0, 0.0, 0.0, 0.0, 0.0])
                h[0] += 1
                h[1] += usd
                if who == taker:                               # empujó el precio
                    h[2 if t["side"] == "B" else 3] += usd
                else:                                          # puso la liquidez
                    h[4] += usd
        kind = self.kinds.get(taker, "otros")
        if kind not in CONFIRMED:                              # el flujo por minuto agrupa solo los confirmados
            kind = "otros"
        m = self.minute.setdefault(coin, {})
        key = f"{kind}|{'compra' if t['side'] == 'B' else 'venta'}"
        m[key] = m.get(key, 0.0) + usd
        self.trades_seen += 1


def load_radar(path: Path = RADAR) -> dict[str, str]:
    """Todas las cuentas del radar con su tipo (también las 'sin confirmar': se estudian un mes)."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {c["address"].lower(): c["kind"] for c in data.get("cuentas", [])}


def load_cohort() -> list[str]:
    if not COHORT.exists():
        return []
    return [a.lower() for a in json.loads(COHORT.read_text(encoding="utf-8")).get("cuentas", [])]


def refresh_radar() -> dict[str, str]:
    """Vuelve a perfilar las cuentas de la cohorte (fija durante el mes). Si no hay cohorte, la crea
    con las 30 primeras del ranking. Las cuentas solo se cambian en la revisión mensual."""
    from .hft import as_dict, scan
    from .sources.hyperliquid import HyperliquidSource
    cohort = load_cohort()
    profiles = scan(HyperliquidSource(), top=COHORT_SIZE, addresses=cohort or None)
    if not cohort:
        COHORT.parent.mkdir(parents=True, exist_ok=True)
        COHORT.write_text(json.dumps({"desde": datetime.now(COT).strftime("%Y-%m-%d"),
                                      "nota": "Cuentas en estudio durante un mes; se revisan y descartan cada mes.",
                                      "cuentas": [p.address for p in profiles]}, indent=1), encoding="utf-8")
    RADAR.parent.mkdir(parents=True, exist_ok=True)
    RADAR.write_text(json.dumps({"actualizado": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                                 "cuentas": [as_dict(p) for p in profiles]}, indent=1), encoding="utf-8")
    return {p.address.lower(): p.kind for p in profiles}


def mm_liquidity(source, makers: list[str], coin: str, price: float, band: float = 0.01) -> tuple[float, float]:
    """USD en órdenes de compra / venta de los creadores de mercado a ±band del precio."""
    bid = ask = 0.0
    for a in makers:
        try:
            orders = source._info({"type": "openOrders", "user": a}) or []
        except Exception:
            continue
        for o in orders:
            if o.get("coin") != coin:
                continue
            px, sz = float(o["limitPx"]), float(o["sz"])
            if abs(px / price - 1) > band:
                continue
            if o["side"] == "B":
                bid += px * sz
            else:
                ask += px * sz
    return bid, ask


def nearest_zone(state: State, coin: str, up: bool) -> str:
    z = state.zones.get(coin)
    px = state.price.get(coin)
    if not z or not px:
        return ""
    longs, shorts = z
    cand = [s for s in shorts if s.center > px] if up else [l for l in longs if l.center < px]
    if not cand:
        return ""
    zz = min(cand, key=lambda q: abs(q.center - px))
    kind = "cortos" if up else "largos"
    return f" → va hacia el pool de {kind} 25-100x en {zz.center:,.0f} ({abs(zz.center / px - 1):.1%})"


def alert(state: State, key: str, title: str, body: str, data: dict) -> None:
    now = time.time()
    if now - state.last_alert.get(key, 0) < COOLDOWN_S:
        return
    state.last_alert[key] = now
    state.alerts_since_beat += 1
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    try:
        with EVENTS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": int(now * 1000), "tipo": key, "titulo": title, **data}, ensure_ascii=False) + "\n")
    except PermissionError:
        log.warning("No pude guardar el aviso en %s (archivo abierto)", EVENTS)
    log.warning("%s | %s", title, body)
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        try:
            from .notify import send_ntfy
            send_ntfy(title, body, "VIGILAR", topic)
        except Exception as exc:
            log.error("ntfy: %s", exc)


HEADER = ["hora_col", "moneda", "precio", "cazador_compra", "cazador_venta", "creador_compra",
          "creador_venta", "otros_compra", "otros_venta", "liq_creadores_compra_1pct", "liq_creadores_venta_1pct"]


def close_minute(state: State, source, makers: list[str], snap: dict | None = None) -> None:
    """Cierra un minuto. `snap` es el acumulado del minuto, ya separado en el hilo principal para que la
    escucha siga recibiendo mientras esto (que consulta la API) corre en segundo plano."""
    ts = (datetime.now(COT) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")   # minuto que se cierra
    if snap is None:
        snap, state.minute = state.minute, {}
    for coin in COINS:
        m = snap.get(coin, {})
        px = state.price.get(coin, 0.0)
        g = lambda k: round(m.get(k, 0.0))
        hunt_net = m.get("cazador|compra", 0.0) - m.get("cazador|venta", 0.0)
        state.net_hist[coin].append(hunt_net)
        bid = ask = 0.0
        if px and makers:
            bid, ask = mm_liquidity(source, makers, coin, px)
            state.book_hist[coin].append((bid, ask))
        state.pending.append([ts, coin, px, g("cazador|compra"), g("cazador|venta"), g("creador de mercado|compra"),
                              g("creador de mercado|venta"), g("otros|compra"), g("otros|venta"), round(bid), round(ask)])
        check_signals(state, coin)
    flush_rows(state)


HOURLY_CSV = Path("data/hft_cuentas_hora.csv")


def heartbeat(state: State, minutes: int) -> str:
    """Línea de estado para la ventana (y, de vez en cuando, para el móvil) aunque no haya avisos."""
    parts = []
    for coin in COINS:
        hist = list(state.net_hist[coin])[-minutes:]
        net = sum(hist)
        px = state.price.get(coin, 0.0)
        side = "compran" if net > 0 else "venden"
        book = state.book_hist[coin][-1] if state.book_hist[coin] else (0.0, 0.0)
        parts.append(f"{coin} {px:,.0f} · cazadores {side} neto ${abs(net) / 1e6:.1f}M · creadores "
                     f"${book[0] / 1e6:.1f}M compra / ${book[1] / 1e6:.1f}M venta a ±1 %")
    seen = state.trades_seen - state.trades_at_last_beat
    state.trades_at_last_beat = state.trades_seen
    alerts = state.alerts_since_beat
    state.alerts_since_beat = 0
    line = (f"✓ Funcionando: {seen:,} operaciones en {minutes} min, "
            f"{'sin avisos' if not alerts else f'{alerts} aviso(s)'} | " + " | ".join(parts))
    if getattr(state, "binance", None) is not None:
        line += "\n   " + state.binance.summary(minutes)
    return line


def close_hour(state: State, snap: dict | None = None) -> None:
    """Guarda, por cuenta de la cohorte y hora: operaciones, volumen, cuánto empujó comprando/vendiendo
    (taker) y cuánta liquidez puso (maker). Con un mes de esto se ve quién es más activo y quién mueve el precio."""
    hour = (datetime.now(COT) - timedelta(hours=1)).strftime("%Y-%m-%d %H:00")
    if snap is None:
        snap, state.hourly = state.hourly, {}
    for addr, kind in state.kinds.items():
        n, usd, tb, ts, mk = snap.get(addr, [0, 0.0, 0.0, 0.0, 0.0])
        state.hour_pending.append([hour, addr, kind, n, round(usd), round(tb), round(ts), round(mk),
                                   state.price.get("BTC", 0.0), state.price.get("ETH", 0.0)])
    try:
        new_file = not HOURLY_CSV.exists()
        HOURLY_CSV.parent.mkdir(parents=True, exist_ok=True)
        with HOURLY_CSV.open("a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new_file:
                w.writerow(["hora_col", "cuenta", "tipo", "operaciones_btc_eth", "usd", "empuja_compra_usd",
                            "empuja_venta_usd", "liquidez_puesta_usd", "precio_btc", "precio_eth"])
            w.writerows(state.hour_pending)
        state.hour_pending = []
    except PermissionError:
        log.warning("El archivo %s está abierto; guardo la hora en memoria.", HOURLY_CSV)


def flush_rows(state: State) -> None:
    """Escribe las filas pendientes. Si el archivo está abierto en Excel (Windows lo bloquea), las guarda
    en memoria y lo vuelve a intentar el minuto siguiente: no se pierde nada ni se corta la escucha."""
    if not state.pending:
        return
    try:
        new_file = not FLOW_CSV.exists()
        FLOW_CSV.parent.mkdir(parents=True, exist_ok=True)
        with FLOW_CSV.open("a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new_file:
                w.writerow(HEADER)
            w.writerows(state.pending)
        state.pending = []
        state.warned_locked = False
    except PermissionError:
        if not state.warned_locked:
            log.warning("El archivo %s está abierto (¿en Excel?). Sigo escuchando y guardo los datos en "
                        "memoria; se escribirán cuando lo cierres.", FLOW_CSV)
            state.warned_locked = True


def check_signals(state: State, coin: str) -> None:
    hist = list(state.net_hist[coin])
    px = state.price.get(coin, 0.0)
    if len(hist) >= 60:
        five = sum(hist[-5:])
        base = [sum(hist[i:i + 5]) for i in range(0, len(hist) - 5)]
        sd = statistics.pstdev(base) or 1.0
        z = (five - statistics.fmean(base)) / sd
        if abs(z) >= Z_PUSH and abs(five) >= MIN_PUSH_USD:
            up = five > 0
            side = "COMPRAN" if up else "VENDEN"
            alert(state, f"empuje-{coin}-{side}", f"🤖 {coin}: los cazadores {side} agresivo",
                  f"Flujo neto 5 min ${five / 1e6:+.1f}M ({z:+.1f}σ) a {px:,.0f}{nearest_zone(state, coin, up)}",
                  {"moneda": coin, "precio": px, "flujo_5m": five, "z": z})
    book = list(state.book_hist[coin])
    if len(book) >= 15:
        avg_bid = statistics.fmean(b for b, _ in book[:-1])
        avg_ask = statistics.fmean(a for _, a in book[:-1])
        bid, ask = book[-1]
        for side_name, now_v, avg_v, up in (("compras", bid, avg_bid, False), ("ventas", ask, avg_ask, True)):
            if avg_v >= MIN_BOOK_USD and now_v < PULL_RATIO * avg_v:
                alert(state, f"retiro-{coin}-{side_name}", f"🏦 {coin}: los creadores de mercado retiran {side_name}",
                      f"Liquidez a ±1 %: ${now_v / 1e6:.2f}M frente a ${avg_v / 1e6:.2f}M de media, a {px:,.0f}"
                      f"{nearest_zone(state, coin, up)} (camino libre {'arriba' if up else 'abajo'})",
                      {"moneda": coin, "precio": px, "ahora": now_v, "media": avg_v, "lado": side_name})


def refresh_zones(state: State, source) -> None:
    from .method.shortliq import short_term_zones
    now = int(time.time() * 1000)
    for coin in COINS:
        try:
            cs = [c for c in source.candles(coin, "1h", now - 8 * 86_400_000, now) if c.t + 3_600_000 <= now]
            state.zones[coin] = short_term_zones(cs)
        except Exception as exc:
            log.error("zonas %s: %s", coin, exc)


async def run(minutes: float | None = None) -> None:
    import websockets
    from .sources.hyperliquid import HyperliquidSource

    source = HyperliquidSource()
    kinds = load_radar()
    stale = (not COHORT.exists() or not RADAR.exists() or time.time() - RADAR.stat().st_mtime > 6 * 3600
             or len(kinds) < len(load_cohort()))
    if not kinds or stale:
        log.warning("Actualizando el estudio de las cuentas desde el ranking (tarda unos minutos)...")
        try:
            kinds = await asyncio.to_thread(refresh_radar)
        except Exception as exc:
            log.error("No pude actualizar el radar (%s); uso la lista guardada", exc)
    state = State(kinds)
    makers = [a for a, k in kinds.items() if k == "creador de mercado"][:12]
    await asyncio.to_thread(refresh_zones, state, source)
    log.warning("Escuchando %s · estudiando %d cuentas (%d cazadores y %d creadores de mercado confirmados)",
                ", ".join(COINS), len(kinds), sum(k == "cazador" for k in kinds.values()), len(makers))
    started = time.time()
    # Binance en paralelo (liquidaciones, interés abierto, volumen agresivo, largos/cortos)
    from . import binance_escucha
    bstate = binance_escucha.BinanceState()
    state.binance = bstate
    stop = lambda: minutes is not None and time.time() - started >= minutes * 60
    binance_task = asyncio.create_task(
        binance_escucha.run(lambda k, t, b, d: alert(state, k, t, b, d), stop, bstate))
    last_minute = int(time.time() // 60)
    last_radar = last_zones = time.time()
    reconnecting = False
    last_hour = int(time.time() // 3600)
    last_beat = time.time()
    last_phone_beat = time.time()
    background: set = set()

    def spawn(coro) -> None:
        """Tareas lentas (API, archivos) en segundo plano: la conexión nunca deja de leer, así el
        servidor no la da por muerta (antes: 'keepalive ping timeout')."""
        task = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)

    async def radar_job() -> None:
        nonlocal makers
        try:
            state.kinds = await asyncio.to_thread(refresh_radar)
            makers = [a for a, k in state.kinds.items() if k == "creador de mercado"][:12]
        except Exception as exc:
            log.error("radar: %s", exc)

    async def phone_beat() -> None:
        try:
            from .notify import send_ntfy
            await asyncio.to_thread(send_ntfy, "💚 Escucha activa", heartbeat(state, 60), "ESTADO",
                                    os.environ["NTFY_TOPIC"])
        except Exception as exc:
            log.error("ntfy: %s", exc)

    while minutes is None or time.time() - started < minutes * 60:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=60, max_size=None,
                                          max_queue=4096) as ws:
                for coin in COINS:
                    await ws.send(json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": coin}}))
                if reconnecting:
                    log.warning("Reconectado: escuchando de nuevo %s", ", ".join(COINS))
                    reconnecting = False
                while minutes is None or time.time() - started < minutes * 60:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        msg = json.loads(raw)
                        if msg.get("channel") == "trades":
                            for t in msg.get("data", []):
                                state.add_trade(t)
                    except asyncio.TimeoutError:
                        pass
                    if int(time.time() // 60) != last_minute:
                        last_minute = int(time.time() // 60)
                        snap, state.minute = state.minute, {}
                        spawn(asyncio.to_thread(close_minute, state, source, list(makers), snap))
                        if time.time() - last_beat >= BEAT_MIN * 60:      # señal de vida en la ventana
                            last_beat = time.time()
                            log.warning(heartbeat(state, BEAT_MIN))
                        if time.time() - last_phone_beat >= PHONE_BEAT_H * 3600 and os.environ.get("NTFY_TOPIC"):
                            last_phone_beat = time.time()
                            spawn(phone_beat())
                        if int(time.time() // 3600) != last_hour:
                            last_hour = int(time.time() // 3600)
                            hsnap, state.hourly = state.hourly, {}
                            spawn(asyncio.to_thread(close_hour, state, hsnap))
                    if time.time() - last_zones > 15 * 60:
                        last_zones = time.time()
                        spawn(asyncio.to_thread(refresh_zones, state, source))
                    if time.time() - last_radar > 6 * 3600:
                        last_radar = time.time()
                        spawn(radar_job())
        except Exception as exc:
            log.error("Conexión perdida (%s: %s); reconectando en 10 s", type(exc).__name__, exc)
            reconnecting = True
            await asyncio.sleep(10)
    binance_task.cancel()


def _disable_quick_edit() -> None:
    """En Windows, un clic dentro de la ventana activa el modo 'Seleccionar' y CONGELA el programa hasta
    pulsar una tecla (las conexiones se caen por falta de respuesta). Se desactiva ese modo."""
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-10)                    # entrada estándar de la consola
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            k32.SetConsoleMode(handle, (mode.value & ~0x0040) | 0x0080)   # sin QuickEdit, con flags extendidos
    except Exception:
        pass


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Escucha 24/7 de la alta frecuencia en Hyperliquid")
    ap.add_argument("--minutos", type=float, help="parar tras N minutos (por defecto, nunca)")
    ap.add_argument("--ntfy-topic", help="tema de ntfy para los avisos (o variable NTFY_TOPIC)")
    args = ap.parse_args(argv)
    if args.ntfy_topic:
        os.environ["NTFY_TOPIC"] = args.ntfy_topic
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    _disable_quick_edit()
    try:
        asyncio.run(run(args.minutos))
    except KeyboardInterrupt:
        print("Escucha detenida.")


if __name__ == "__main__":
    main()
