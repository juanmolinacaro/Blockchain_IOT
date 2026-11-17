"""Nasdaq minuto a minuto para la escucha (corre en el computador de Juan).

Para medir si las caídas de BTC vienen de la bolsa ("se desplomaron las tecnológicas") o si la noticia es
la disculpa, la escucha guarda también el futuro del Nasdaq 100 (NQ=F, cotiza casi 24 h de domingo a
viernes) en `data/nasdaq_minuto.csv`. Después, `copytrading causa` compara cada movimiento fuerte de BTC
con lo que hizo el Nasdaq antes y durante.

Fuente: el gráfico público de Yahoo Finanzas (sin clave). Puede llegar con unos minutos de retraso; no
importa, porque es para estudiar después, no para avisar. Cada 5 minutos se piden las velas del día y se
añaden solo las nuevas ya cerradas; al arrancar se piden 5 días para rellenar lo que faltó mientras el
equipo estuvo apagado.
"""
from __future__ import annotations

import asyncio
import csv
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("escucha")
COT = timezone(timedelta(hours=-5))
SYMBOLS = {"NQ=F": "NASDAQ"}
CSV_PATH = Path("data/nasdaq_minuto.csv")
HEADER = ["hora_col", "indice", "precio", "volumen"]
URLS = ["https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
        "https://query2.finance.yahoo.com/v8/finance/chart/{sym}"]
POLL_S = 5 * 60
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def parse_chart(payload: dict, name: str, after_ts: int, now_ts: int) -> list[list]:
    """Filas [hora_col, índice, cierre, volumen] de las velas de 1 m ya cerradas y posteriores a `after_ts`."""
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return []
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    vols = quote.get("volume") or []
    rows = []
    for i, ts in enumerate(stamps):
        close = closes[i] if i < len(closes) else None
        if close is None or ts <= after_ts or ts + 60 > now_ts:      # sin dato, ya guardada o aún abierta
            continue
        vol = vols[i] if i < len(vols) and vols[i] is not None else 0
        hora = datetime.fromtimestamp(ts, COT).strftime("%Y-%m-%d %H:%M")
        rows.append([hora, name, round(float(close), 2), int(vol)])
    return rows


def last_saved(path: Path = CSV_PATH) -> dict[str, int]:
    """Última vela guardada de cada índice (segundos), para no repetir filas al reiniciar."""
    out: dict[str, int] = {}
    if not path.exists():
        return out
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ts = int(datetime.strptime(row["hora_col"][:16], "%Y-%m-%d %H:%M").replace(tzinfo=COT).timestamp())
                out[row["indice"]] = max(out.get(row["indice"], 0), ts)
    except (OSError, KeyError, ValueError):
        pass
    return out


def fetch(session, sym: str, rng: str) -> dict:
    last_exc: Exception | None = None
    for url in URLS:
        try:
            r = session.get(url.format(sym=sym), params={"interval": "1m", "range": rng}, headers=UA, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as exc:          # probar la otra dirección
            last_exc = exc
    raise last_exc or RuntimeError("sin respuesta")


def write_rows(rows: list[list], pending: list[list]) -> list[list]:
    """Escribe; si el archivo está abierto en Excel devuelve las filas para intentarlo luego."""
    pending = pending + rows
    if not pending:
        return []
    try:
        new = not CSV_PATH.exists()
        CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CSV_PATH.open("a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(HEADER)
            w.writerows(pending)
        return []
    except PermissionError:
        log.warning("El archivo %s está abierto; guardo los datos del Nasdaq en memoria.", CSV_PATH)
        return pending


def poll_once(session, saved: dict[str, int], rng: str) -> list[list]:
    now = int(time.time())
    rows = []
    for sym, name in SYMBOLS.items():
        new = parse_chart(fetch(session, sym, rng), name, saved.get(name, 0), now)
        if new:
            saved[name] = int(datetime.strptime(new[-1][0], "%Y-%m-%d %H:%M").replace(tzinfo=COT).timestamp())
        rows += new
    return rows


async def run(should_stop) -> None:
    import requests

    session = requests.Session()
    saved = await asyncio.to_thread(last_saved)
    pending: list[list] = []
    first, last_error, rng = True, 0.0, "5d"
    while not should_stop():
        try:
            rows = await asyncio.to_thread(poll_once, session, saved, rng)
            rng = "1d"
            pending = await asyncio.to_thread(write_rows, rows, pending)
            if first:
                first = False
                tail = f"último {rows[-1][2]:,.0f} ({rows[-1][0][11:]})" if rows else "bolsa sin velas nuevas"
                log.warning("Nasdaq datos ✓ %d velas guardadas · %s", len(rows), tail)
            if last_error:
                log.warning("Nasdaq disponible de nuevo ✓")
                last_error = 0.0
        except Exception as exc:
            if time.time() - last_error >= 1800:              # un aviso cada 30 min como mucho
                last_error = time.time()
                log.error("Nasdaq no disponible (%s: %s); reintento cada 5 min", type(exc).__name__, exc)
        for _ in range(POLL_S):
            if should_stop():
                return
            await asyncio.sleep(1)
