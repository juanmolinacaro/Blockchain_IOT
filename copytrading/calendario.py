"""Calendario de noticias grandes de EE. UU. (13 nov 2026). Juan: "la noticia es la chispa; hay que usarla
a favor de la liquidez". Las horas se guardan en hora de Nueva York y se pasan a hora de Colombia teniendo
en cuenta el horario de verano de EE. UU. (en invierno coinciden; en verano Colombia va una hora menos).
El archivo `data/calendario.json` se lee de GitHub, así se añaden eventos sin reiniciar la escucha."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

COT = timezone(timedelta(hours=-5))
URL = ("https://raw.githubusercontent.com/juanmolinacaro/Blockchain_IOT/"
       "claude/onchain-replication-strategy-8naui6/data/calendario.json")
LOCAL = Path("data/calendario.json")


def load() -> dict:
    import urllib.request
    try:
        with urllib.request.urlopen(URL, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        try:
            return json.loads(LOCAL.read_text(encoding="utf-8"))
        except Exception:
            return {}


def ny_to_cot(day: date, hhmm: str) -> datetime:
    from .causa import _ny_offset
    h, m = (int(x) for x in hhmm.split(":"))
    noon_utc = datetime(day.year, day.month, day.day, 17, tzinfo=timezone.utc)
    ny = timezone(timedelta(hours=_ny_offset(noon_utc)))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=ny).astimezone(COT)


def events_for(cal: dict, day: date) -> list[dict]:
    """Eventos de ese día (hora Colombia), los fijos y los que se repiten cada semana."""
    out = []
    for e in cal.get("eventos", []):
        if e.get("fecha") == day.isoformat():
            out.append({**e, "cot": ny_to_cot(day, e["hora_ny"])})
    for e in cal.get("recurrentes", []):
        if day.weekday() == e.get("dia_semana"):
            out.append({**e, "cot": ny_to_cot(day, e["hora_ny"])})
    return sorted(out, key=lambda e: e["cot"])


def describe(events: list[dict]) -> str:
    if not events:
        return "📅 Hoy sin noticias grandes de EE. UU. en el calendario."
    return "📅 Hoy: " + " · ".join(f"{e['cot']:%H:%M} {e['nombre']}" + (" ⚠ ALTO" if e.get("impacto") == "alto" else "")
                                   for e in events)
