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
   * **las cuentas que ganan** empujan fuerte en una dirección (flujo neto de 5 min muy por encima de lo
     normal). Desde el 7 nov: los "cazadores" del radar resultaron perdedores (una cuenta agresiva no es
     una cuenta lista), así que la alerta sigue a las cuentas de la cohorte que GANAN desde que entraron
     al estudio (`rendimiento.py`, se renueva cada 6 h). Si aún no se sabe quién gana, usa los cazadores,
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
REVIEW_HOUR = 20             # revisión diaria de los avisos (hora Colombia): ajustar cada día, no al mes


class State:
    def __init__(self, kinds: dict[str, str]):
        self.kinds = kinds                                       # dirección -> tipo
        self.winners: set[str] = set()                          # cuentas de la cohorte que ganan en el estudio
        self.minute: dict[str, dict[str, float]] = {}           # moneda -> acumulado del minuto
        self.price: dict[str, float] = {}
        self.net_hist: dict[str, deque] = {c: deque(maxlen=180) for c in COINS}      # flujo neto/min (3 h)
        self.book_hist: dict[str, deque] = {c: deque(maxlen=30) for c in COINS}     # (bid, ask) por minuto
        self.last_alert: dict[str, float] = {}
        self.zones: dict[str, tuple[list, list]] = {}
        self.trend: dict[str, str] = {}                         # moneda -> ALCISTA | BAJISTA (EMA 50 diaria)
        self.px_hist: dict[str, deque] = {c: deque(maxlen=60) for c in COINS}       # cierre por minuto (1 h)
        self.win_hist: dict[str, deque] = {c: deque(maxlen=60) for c in COINS}      # empuje neto de las ganadoras/min
        self.crowd_hist: dict[str, deque] = {c: deque(maxlen=60) for c in COINS}    # empuje neto del resto (público)/min
        self.whale_pos: dict[str, deque] = {}                    # (hora, posición neta USD de las que ganan)
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
        side = "compra" if t["side"] == "B" else "venta"
        key = f"{kind}|{side}"
        m[key] = m.get(key, 0.0) + usd
        if taker in self.winners:                              # aparte: lo que empujan las cuentas que ganan
            m[f"ganadoras|{side}"] = m.get(f"ganadoras|{side}", 0.0) + usd
        self.trades_seen += 1

    @property
    def signal_group(self) -> str:
        """De quién es el flujo que vigila la alerta de empuje."""
        return "ganadoras" if self.winners else "cazador"

    @property
    def signal_name(self) -> str:
        return "las cuentas que ganan" if self.winners else "los cazadores"


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


def mm_liquidity(source, makers: list[str], coin: str, price: float, band: float = 0.01) -> tuple[float, float] | None:
    """USD en órdenes de compra / venta de los creadores de mercado a ±band del precio.
    Devuelve None si alguna consulta falla (p. ej. límite de la API en plena caída): un fallo NO es
    'liquidez cero' (el 5 nov dio avisos falsos de retiro por eso)."""
    bid = ask = 0.0
    for a in makers:
        try:
            orders = source._info({"type": "openOrders", "user": a}) or []
        except Exception:
            return None
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
          "creador_venta", "otros_compra", "otros_venta", "liq_creadores_compra_1pct", "liq_creadores_venta_1pct",
          "ganadoras_compra", "ganadoras_venta"]


def close_minute(state: State, source, makers: list[str], snap: dict | None = None) -> None:
    """Cierra un minuto. `snap` es el acumulado del minuto, ya separado en el hilo principal para que la
    escucha siga recibiendo mientras esto (que consulta la API) corre en segundo plano."""
    ts = (datetime.now(COT) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")   # minuto que se cierra
    if snap is None:
        snap, state.minute = state.minute, {}
    for coin in COINS:
        m = snap.get(coin, {})
        px = state.price.get(coin, 0.0)
        if px:
            state.px_hist[coin].append(px)
        g = lambda k: round(m.get(k, 0.0))
        state.win_hist[coin].append(m.get("ganadoras|compra", 0.0) - m.get("ganadoras|venta", 0.0))
        state.crowd_hist[coin].append(m.get("otros|compra", 0.0) - m.get("otros|venta", 0.0))
        grp = state.signal_group
        state.net_hist[coin].append(m.get(f"{grp}|compra", 0.0) - m.get(f"{grp}|venta", 0.0))
        bid = ask = ""
        if px and makers:
            got = mm_liquidity(source, makers, coin, px)
            if got is not None:
                bid, ask = got
                state.book_hist[coin].append(got)
        state.pending.append([ts, coin, px, g("cazador|compra"), g("cazador|venta"), g("creador de mercado|compra"),
                              g("creador de mercado|venta"), g("otros|compra"), g("otros|venta"),
                              round(bid) if bid != "" else "", round(ask) if ask != "" else "",
                              g("ganadoras|compra"), g("ganadoras|venta")])
        check_signals(state, coin)
        check_squeeze(state, coin)
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
        who = "ganadoras" if state.winners else "cazadores"
        parts.append(f"{coin} {px:,.0f} · {who} {side} neto ${abs(net) / 1e6:.1f}M · creadores "
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


def rotate_old_flow(path: Path | None = None) -> Path | None:
    """Si el CSV del flujo tiene la cabecera de una versión anterior (menos columnas), lo renombra para
    no mezclar formatos y empieza uno nuevo. Devuelve el nombre del archivo guardado."""
    path = path or FLOW_CSV
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        first = fh.readline().strip()
    if first == ",".join(HEADER):
        return None
    old = path.with_name(f"{path.stem}_hasta_{datetime.now(COT):%Y-%m-%d_%H%M}{path.suffix}")
    path.rename(old)
    log.warning("Formato nuevo del flujo (con las cuentas que ganan): el anterior queda en %s", old.name)
    return old


def refresh_winners(state: State) -> None:
    """Cuentas de la cohorte que ganan desde que entraron al estudio (regla de Juan: una buena ballena es
    la que gana). Si falla, conserva las anteriores."""
    from .rendimiento import cohort, last_winners, save, scan, select_winners
    from .sources.hyperliquid import HyperliquidSource
    addresses, desde = cohort(COHORT)
    if not addresses:
        return
    rows = scan(HyperliquidSource(), addresses, desde)
    if not rows:
        return
    previous = state.winners or last_winners()            # al reiniciar, las de la última revisión guardada
    state.winners = select_winners(rows, previous)
    try:
        save(rows, winners=state.winners)
    except OSError:
        pass
    log.warning("Cuentas que ganan en el estudio: %d de %d (la alerta de empuje las sigue a ellas)",
                len(state.winners), len(rows))


def flush_rows(state: State) -> None:
    """Escribe las filas pendientes. Si el archivo está abierto en Excel (Windows lo bloquea), las guarda
    en memoria y lo vuelve a intentar el minuto siguiente: no se pierde nada ni se corta la escucha."""
    if not state.pending:
        return
    try:
        rotate_old_flow()
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
            icon = "💰" if state.winners else "🤖"
            # Sin ficha desde el 10 nov (decisión de Juan): la dirección del aviso 💰 acertó 43 % a 60 min
            # (21 casos). Queda como información; las fichas van en las rupturas de compresión.
            card_text, card = "", None
            fresh = time.time() - state.last_alert.get(f"empuje-{coin}-{side}", 0) >= COOLDOWN_S
            action = winners_action(state, coin, up) if state.winners and fresh else None
            if action:
                card_text = f"\n{action['texto']}" + card_text
            alert(state, f"empuje-{coin}-{side}", f"{icon} {coin}: {state.signal_name} {side} agresivo",
                  f"Flujo neto 5 min ${five / 1e6:+.1f}M ({z:+.1f}σ) a {px:,.0f}{nearest_zone(state, coin, up)}"
                  f"{card_text}",
                  {"moneda": coin, "precio": px, "flujo_5m": five, "z": z, "grupo": state.signal_group,
                   **({"ficha": card} if card else {}),
                   **({"abren_usd": action["abren"], "cierran_usd": action["cierran"]} if action else {})})
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


def winners_action(state: State, coin: str, up: bool, minutes: int = 6) -> dict | None:
    """¿Las cuentas que ganan ABREN posición en esa dirección o solo CIERRAN la contraria? No es lo mismo:
    el 9 nov a las 12:08 el aviso "venden $22,5M" fue una sola cuenta cerrando largos (salir no es apostar
    a la baja). Consulta sus operaciones agresivas de los últimos minutos."""
    source = getattr(state, "source", None)
    if source is None:
        return None
    since = int(time.time() * 1000) - minutes * 60_000
    side = "B" if up else "A"
    opening = "Open Long" if up else "Open Short"
    closing = "Close Short" if up else "Close Long"
    abren = cierran = 0.0
    cuentas = 0
    for a in state.winners:
        try:
            fills = source._info({"type": "userFillsByTime", "user": a, "startTime": since, "aggregateByTime": True}) or []
        except Exception:
            continue
        mine = [f for f in fills if f.get("coin") == coin and f.get("crossed") and f.get("side") == side]
        if mine:
            cuentas += 1
        for f in mine:
            usd = float(f["px"]) * float(f["sz"])
            if f.get("dir") == opening:
                abren += usd
            elif f.get("dir") == closing:
                cierran += usd
    if not abren and not cierran:
        return None
    verbo, contra = ("abren largos", "cierran cortos") if up else ("abren cortos", "cierran largos")
    if abren >= cierran:
        texto = f"🔎 {cuentas} cuenta(s): {verbo} ${abren / 1e6:.1f}M (apuestan a {'subir' if up else 'bajar'})"
        if cierran:
            texto += f" y {contra} ${cierran / 1e6:.1f}M"
    else:
        texto = (f"🔎 {cuentas} cuenta(s): sobre todo {contra} ${cierran / 1e6:.1f}M (salen de su posición, no "
                 f"apuestan a {'subir' if up else 'bajar'}: señal más débil)")
        if abren:
            texto += f"; {verbo} ${abren / 1e6:.1f}M"
    return {"texto": texto, "abren": round(abren), "cierran": round(cierran)}


CARD_MIN_R = 1.5          # la ficha solo propone la operación si el objetivo paga al menos 1,5 veces el riesgo
CARD_STOP_PAD = 0.0015    # stop un 0,15 % más allá del extremo de los últimos 30 minutos
CARD_LOOKBACK = 30
CARD_TP_FRONT = 0.004     # TP1 un 0,4 % antes del centro del pool: los barridos se quedan cortos del núcleo
                          # (vie 6 nov: mínimo 74.842 con núcleo 74.711; dom 8 nov: 73.457 con pool ~73.2xx)


def trade_card(state: State, coin: str, up: bool, now_ms: int | None = None) -> tuple[str, dict | None]:
    """Operación ya armada para el aviso de las cuentas que ganan (la ventaja es de ~2 minutos: no hay
    tiempo de calcular). Reglas de Juan: solo a favor de la tendencia, no viernes/sábado, stop fuera del
    pool (más allá del extremo reciente), objetivo en el siguiente pool de liquidez que pague ≥ 1,5R,
    asegurar en TP1 y dejar correr. Devuelve (texto para el aviso, datos para medirla después)."""
    from .method.monitor import trading_allowed
    px = state.price.get(coin, 0.0)
    trend = state.trend.get(coin, "")
    side = "LARGO" if up else "CORTO"
    if not px:
        return "", None
    if not trading_allowed(now_ms if now_ms is not None else int(time.time() * 1000)):
        return "\n📋 Hoy no se opera (viernes/sábado hasta el domingo 1 pm).", None
    if trend and trend != ("ALCISTA" if up else "BAJISTA"):
        return (f"\n⚠ Contra la tendencia ({trend.lower()}): no abrir {side.lower()}. Si tienes una posición a "
                f"favor de la tendencia, asegura ganancias."), None
    hist = list(state.px_hist[coin])[-CARD_LOOKBACK:] or [px]
    stop = min(hist) * (1 - CARD_STOP_PAD) if up else max(hist) * (1 + CARD_STOP_PAD)
    risk = abs(px - stop)
    z = state.zones.get(coin)
    pools = sorted((s.center for s in z[1] if s.center > px), key=lambda c: c - px) if z and up else \
        sorted((l.center for l in z[0] if l.center < px), key=lambda c: px - c) if z else []
    pools = [c * (1 - CARD_TP_FRONT) if up else c * (1 + CARD_TP_FRONT) for c in pools]
    target = next((c for c in pools if risk and abs(c - px) / risk >= CARD_MIN_R), None)
    if not risk or target is None:
        best = f" (el pool más cercano paga {abs(pools[0] - px) / risk:.1f}R)" if pools and risk else ""
        return f"\n📋 Sin operación: ningún pool paga ≥ {CARD_MIN_R}R con el stop en {stop:,.0f}{best}.", None
    r = abs(target - px) / risk
    card = {"lado": "long" if up else "short", "entrada": round(px, 2), "stop": round(stop, 2),
            "tp1": round(target, 2), "r": round(r, 2)}
    return (f"\n📋 FICHA {side} {coin}: entrada ~{px:,.0f} · stop {stop:,.0f} · TP1 {target:,.0f} ({r:.1f}R) · "
            f"en TP1 asegura y deja correr con stop en la entrada."), card


SQUEEZE_RANGE = 0.004       # 60 min con rango < 0,4 %: el precio se comprime (se gesta un movimiento)
SQUEEZE_COOLDOWN_S = 3 * 3600


CROWD_MIN = 2_000_000
CROWDED_LONG = 2.0       # cuentas de Binance: ≥ 2 largos por corto y funding positivo = la mayoría cargada de largos
CROWDED_SHORT = 0.8


def confirmation(state: State, coin: str) -> dict:
    """Junta lo que el radar mide y ha mostrado ventaja (idea de Juan, 10 nov): tendencia, lo que hace la
    mayoría (el público empuja en contra del movimiento que viene: 12 de 14 casos), las ballenas que ganan
    (su posición y si aumentan), Binance (interés abierto y largos/cortos de las cuentas) y el imán de
    liquidez. Cada pieza vota −1 (bajista), +1 (alcista) o 0. Devuelve votos, total y texto."""
    votos: dict[str, int] = {}
    det: list[str] = []
    tr = state.trend.get(coin, "")
    if tr:
        votos["tendencia"] = -1 if tr == "BAJISTA" else 1
        det.append(f"tendencia {tr.lower()}")
    crowd = sum(list(state.crowd_hist.get(coin, []))[-30:])
    if abs(crowd) >= CROWD_MIN:
        votos["público"] = -1 if crowd > 0 else 1
        det.append(f"el público {'compra' if crowd > 0 else 'vende'} ${abs(crowd) / 1e6:.1f}M (combustible "
                   f"{'abajo' if crowd > 0 else 'arriba'})")
    wp = list(state.whale_pos.get(coin, []))
    if wp:
        now_v = wp[-1][1]
        old_v = wp[0][1]
        if abs(now_v) >= 1_000_000:
            votos["ballenas"] = -1 if now_v < 0 else 1
            change = abs(now_v) - abs(old_v)
            trend_txt = "aumentan" if change > 0.05 * abs(old_v or 1) else "reducen" if change < -0.05 * abs(old_v or 1) else "mantienen"
            det.append(f"las que ganan en {'corto' if now_v < 0 else 'largo'} ${abs(now_v) / 1e6:.1f}M ({trend_txt})")
    rows = (getattr(getattr(state, "binance", None), "recent", {}) or {}).get(coin, [])[-60:]
    if len(rows) >= 30 and rows[0][6] and rows[-1][6]:
        oi = rows[-1][6] / rows[0][6] - 1
        lc0 = next((r[11] for r in rows if r[11] != ""), None)
        lc1 = next((r[11] for r in reversed(rows) if r[11] != ""), None)
        if oi > 0.003 and lc0 is not None and lc1 is not None and lc1 != lc0:
            votos["binance"] = -1 if lc1 > lc0 else 1
            det.append(f"Binance: interés abierto {oi * 100:+.1f} % y las cuentas más {'largas' if lc1 > lc0 else 'cortas'}")
    if rows:
        lc = next((r[11] for r in reversed(rows) if r[11] != ""), None)
        fund = rows[-1][7]
        if lc is not None and lc >= CROWDED_LONG and fund > 0:
            votos["mayoría"] = -1
            det.append(f"la mayoría sobreapalancada en largos ({lc:.2f} largos por corto, funding +)")
        elif lc is not None and lc <= CROWDED_SHORT and fund < 0:
            votos["mayoría"] = 1
            det.append(f"la mayoría sobreapalancada en cortos ({lc:.2f} largos por corto, funding −)")
    z = state.zones.get(coin)
    px = state.price.get(coin)
    if z and px:
        below = sum(l.usd for l in z[0] if px * 0.97 <= l.center < px)
        above = sum(s.usd for s in z[1] if px < s.center <= px * 1.03)
        if below > 1.5 * above or above > 1.5 * below:
            votos["imán"] = -1 if below > above else 1
            det.append(f"imán de liquidez {'abajo' if below > above else 'arriba'}")
    total = sum(votos.values())
    n = len(votos)
    if total < 0:
        txt = f"🎯 Confirmación BAJISTA {sum(v < 0 for v in votos.values())}/{n}"
    elif total > 0:
        txt = f"🎯 Confirmación ALCISTA {sum(v > 0 for v in votos.values())}/{n}"
    else:
        txt = f"🎯 Sin confirmación (0 de {n})"
    return {"votos": votos, "total": total, "n": n, "texto": txt + (": " + "; ".join(det) if det else "")}


def check_squeeze(state: State, coin: str) -> None:
    """Aviso 🗜 cuando el precio lleva 60 minutos apretado (como el triángulo del 9 nov), con lo que hacen
    las cuentas mientras tanto: así se ve quién se posiciona antes de la ruptura. `copytrading episodios`
    mide después hacia dónde rompió cada compresión y qué se repite antes de cada lado."""
    hist = list(state.px_hist[coin])
    if len(hist) < 60:
        return
    rng = max(hist) / min(hist) - 1
    if rng >= SQUEEZE_RANGE or time.time() - state.last_alert.get(f"compresion-{coin}", 0) < SQUEEZE_COOLDOWN_S:
        return
    px = hist[-1]
    win = list(state.win_hist.get(coin, []))[-30:] if hasattr(state, "win_hist") else []
    wnet = sum(win)
    book = list(state.book_hist[coin])
    lib = ""
    if len(book) >= 10:
        now_b, now_a = book[-1]
        avg_b = statistics.fmean(b for b, _ in book[:-1]) or 1
        avg_a = statistics.fmean(a for _, a in book[:-1]) or 1
        lib = f" · libro de los creadores: compras ×{now_b / avg_b:.1f}, ventas ×{now_a / avg_a:.1f} de lo normal"
    crowd = sum(list(state.crowd_hist.get(coin, []))[-30:])
    oi_txt = ""
    rows = (getattr(getattr(state, "binance", None), "recent", {}) or {}).get(coin, [])[-30:]
    if len(rows) >= 2 and rows[0][6] and rows[-1][6]:
        oi_txt = f" · interés abierto Binance {(rows[-1][6] / rows[0][6] - 1) * 100:+.2f} % en 30 min"
    hint = ""
    if abs(crowd) >= 2_000_000:          # biblioteca de episodios (10 nov): el público suele estar del lado equivocado
        hint = (f"\n👥 El público {'COMPRA' if crowd > 0 else 'VENDE'} agresivo ${abs(crowd) / 1e6:.1f}M en 30 min{oi_txt}: "
                f"antes de las caídas fuertes solía comprar y antes de las subidas, vender → ojo ruptura "
                f"{'ABAJO' if crowd > 0 else 'ARRIBA'}")
    elif oi_txt:
        hint = f"\n👥 Público equilibrado{oi_txt}"
    conf = confirmation(state, coin)
    up, down = nearest_zone(state, coin, True), nearest_zone(state, coin, False)
    who = (f"las que ganan {'compran' if wnet > 0 else 'venden'} neto ${abs(wnet) / 1e6:.1f}M en 30 min"
           if state.winners and wnet else "las que ganan quietas")
    alert(state, f"compresion-{coin}", f"🗜 {coin}: precio comprimido (se gesta un movimiento)",
          f"Rango 60 min {rng * 100:.2f} % en {px:,.0f} · {who}{lib}{hint}\n{conf['texto']}\nArriba{up or ': sin pool cercano'}\n"
          f"Abajo{down or ': sin pool cercano'}\nNo entrar en la ruptura: esperar la zona del plan.",
          {"moneda": coin, "precio": px, "rango": rng, "ganadoras_30m": wnet, "publico_30m": round(crowd),
           "confirmacion": conf["total"], "votos": conf["votos"]})


BOX_BARS = 12            # caja = últimas 12 velas de 1H
BOX_PCT = 0.2            # "comprimida" = su rango está entre el 20 % más estrecho del historial


def compression_break(candles_1h: list, trend: str, n: int = BOX_BARS, pct: float = BOX_PCT) -> dict | None:
    """¿La última vela de 1H CERRADA rompe una caja comprimida a favor de la tendencia? (idea de Juan, 10 nov:
    "hay estructuras que se repiten; se veía claro el short"). Estudio BTC/ETH/SOL 1H, ~208 días: rupturas a
    favor de la tendencia 156 casos, +0,11R (TP 1R, 54 % aciertos) a +0,17R (TP 1,5R) por operación antes de
    comisiones; en contra ~0R. Devuelve la ficha (entrada al cierre, stop al otro lado de la caja)."""
    if len(candles_1h) < n + 200 or trend not in ("ALCISTA", "BAJISTA"):
        return None
    ranges = []
    for i in range(n, len(candles_1h)):
        w = candles_1h[i - n:i]
        ranges.append(max(k.h for k in w) / min(k.l for k in w) - 1)
    thr = sorted(ranges)[int(len(ranges) * pct)]
    box = candles_1h[-n - 1:-1]
    last = candles_1h[-1]
    hi, lo = max(k.h for k in box), min(k.l for k in box)
    if hi / lo - 1 > thr:
        return None
    if trend == "BAJISTA" and last.c < lo:
        stop = hi * 1.001
        return {"lado": "short", "entrada": last.c, "stop": round(stop, 2), "caja": (lo, hi),
                "tp1": round(last.c - (stop - last.c), 2), "tp2": round(last.c - 2 * (stop - last.c), 2)}
    if trend == "ALCISTA" and last.c > hi:
        stop = lo * 0.999
        return {"lado": "long", "entrada": last.c, "stop": round(stop, 2), "caja": (lo, hi),
                "tp1": round(last.c + (last.c - stop), 2), "tp2": round(last.c + 2 * (last.c - stop), 2)}
    return None


def check_breakouts(state: State, source) -> None:
    """Al cerrar cada hora: aviso 📉/📈 si BTC o ETH rompen una compresión de 1H a favor de la tendencia."""
    from .method.monitor import trading_allowed
    now = int(time.time() * 1000)
    if not trading_allowed(now):
        return
    for coin in COINS:
        try:
            cs = [c for c in source.candles(coin, "1h", now - 2500 * 3_600_000, now) if c.t + 3_600_000 <= now]
        except Exception as exc:
            log.error("ruptura %s: %s", coin, exc)
            continue
        card = compression_break(cs, state.trend.get(coin, ""))
        if not card:
            continue
        short = card["lado"] == "short"
        lo, hi = card["caja"]
        conf = confirmation(state, coin)
        agree = (conf["total"] < 0) if short else (conf["total"] > 0)
        alert(state, f"ruptura-{coin}-{card['lado']}",
              f"{'📉' if short else '📈'} {coin}: rompe la compresión {'hacia abajo' if short else 'hacia arriba'} "
              f"a favor de la tendencia",
              f"Caja de 12 h {lo:,.0f}–{hi:,.0f}; cierre 1H en {card['entrada']:,.0f}\n"
              f"📋 FICHA {'CORTO' if short else 'LARGO'} {coin}: entrada ~{card['entrada']:,.0f} · stop {card['stop']:,.0f} · "
              f"TP1 {card['tp1']:,.0f} (1R, cierra la mitad y stop a la entrada) · TP2 {card['tp2']:,.0f} (2R)"
              f"{nearest_zone(state, coin, not short)}\n{conf['texto']}\n"
              f"{'✅ Los datos confirman la ruptura' if agree else '⚠ Los datos NO la confirman: más riesgo de falsa ruptura'}",
              {"moneda": coin, "precio": card["entrada"], "confirmada": agree, "confirmacion": conf["total"],
               "votos": conf["votos"],
               "ficha": {k: card[k] for k in ("lado", "entrada", "stop", "tp1")} | {"r": 1.0}})


def refresh_zones(state: State, source) -> None:
    from .method.shortliq import short_term_zones
    now = int(time.time() * 1000)
    for coin in COINS:
        try:
            cs = [c for c in source.candles(coin, "1h", now - 8 * 86_400_000, now) if c.t + 3_600_000 <= now]
            state.zones[coin] = short_term_zones(cs)
            from .method.monitor import trend_state
            c4 = source.candles(coin, "4h", now - 830 * 86_400_000, now)
            state.trend[coin] = trend_state(c4)[0]
        except Exception as exc:
            log.error("zonas %s: %s", coin, exc)
    refresh_whales(state, source)


def refresh_whales(state: State, source) -> None:
    """Posición neta (USD; corto en negativo) de las cuentas que ganan en BTC y ETH, cada 15 min, con
    historia de 6 h para saber si aumentan o reducen."""
    if not state.winners:
        return
    tot = {c: 0.0 for c in COINS}
    for a in state.winners:
        try:
            st = source._info({"type": "clearinghouseState", "user": a}) or {}
        except Exception:
            return                                   # mejor sin dato que con dato a medias
        for ap in st.get("assetPositions", []):
            p = ap.get("position", {})
            if p.get("coin") in tot:
                tot[p["coin"]] += float(p.get("szi") or 0) * float(p.get("entryPx") or 0)
    now = time.time()
    for c in COINS:
        h = state.whale_pos.setdefault(c, deque(maxlen=25))       # 25 × 15 min ≈ 6 h
        h.append((now, tot[c]))


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
    state.source = source
    makers = [a for a, k in kinds.items() if k == "creador de mercado"][:12]
    await asyncio.to_thread(refresh_zones, state, source)
    try:
        await asyncio.to_thread(refresh_winners, state)
    except Exception as exc:
        log.error("No pude revisar quién gana (%s); la alerta sigue a los cazadores", exc)
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
    # Nasdaq (futuro NQ) para medir si las caídas de BTC vienen de la bolsa: `copytrading causa`
    from . import nasdaq_escucha
    nasdaq_task = asyncio.create_task(nasdaq_escucha.run(stop))
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
        try:
            await asyncio.to_thread(refresh_winners, state)
        except Exception as exc:
            log.error("rendimiento: %s", exc)

    review = {"day": "", "winners": set(state.winners)}

    async def review_job() -> None:
        from .avisos import daily_review
        try:
            text = await asyncio.to_thread(daily_review, source, EVENTS, set(state.winners), review["winners"])
        except Exception as exc:
            log.error("revisión diaria: %s", exc)
            return
        review["winners"] = set(state.winners)
        try:
            from collections import Counter
            from .episodios import build, default_files
            eps = await asyncio.to_thread(lambda: build(*default_files()))
            cnt = Counter(e.tipo for e in eps)
            if cnt:
                text += "\nEpisodios guardados: " + " · ".join(f"{k} {v}" for k, v in sorted(cnt.items()))
        except Exception as exc:
            log.error("episodios: %s", exc)
        log.warning("📊 Revisión del día\n%s", text)
        try:
            with Path("data/revision_diaria.txt").open("a", encoding="utf-8") as fh:
                fh.write(f"== {datetime.now(COT):%Y-%m-%d %H:%M}\n{text}\n\n")
        except OSError:
            pass
        if os.environ.get("NTFY_TOPIC"):
            try:
                from .notify import send_ntfy
                await asyncio.to_thread(send_ntfy, "📊 Revisión del día", text, "ESTADO", os.environ["NTFY_TOPIC"])
            except Exception as exc:
                log.error("ntfy: %s", exc)

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
                        now_cot = datetime.now(COT)
                        if now_cot.hour == REVIEW_HOUR and review["day"] != now_cot.strftime("%Y-%m-%d"):
                            review["day"] = now_cot.strftime("%Y-%m-%d")
                            spawn(review_job())
                        if int(time.time() // 3600) != last_hour:
                            last_hour = int(time.time() // 3600)
                            hsnap, state.hourly = state.hourly, {}
                            spawn(asyncio.to_thread(close_hour, state, hsnap))
                            spawn(asyncio.to_thread(check_breakouts, state, source))
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
    nasdaq_task.cancel()


def _keep_awake() -> None:
    """En Windows, impide que el equipo se suspenda solo mientras la escucha corre (el 5 nov se durmió de
    23:42 a 09:51 y se perdió la ruptura de las 7 am). No evita la suspensión al cerrar la tapa."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception:
        pass


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
    _keep_awake()
    try:
        asyncio.run(run(args.minutos))
    except KeyboardInterrupt:
        print("Escucha detenida.")


if __name__ == "__main__":
    main()
