"""Rendimiento de las cuentas en estudio: ¿ganan o solo mueven dinero?

Regla de Juan (7 nov 2026): "una buena ballena es la que gana. No vamos a seguir a una ballena que solo
mueve dinero y pierde: esas son las que van a salir el primer mes". El radar de alta frecuencia mide
CÓMO opera una cuenta (agresiva, mucha rotación); esto mide si GANA. Se descubrió con `0xf71a…`: la
marcamos como "cazador" del barrido del 5 nov y en realidad estaba capitulando; perdió $1,17M esa semana.

Para cada cuenta de la cohorte (`data/hft_cohorte.json`), con el portafolio público de Hyperliquid:
ganancia o pérdida de la semana, de los últimos 30 días y **desde que entró al estudio**, volumen, y
**cuánto gana por cada $10.000 movidos** (eficiencia). Veredicto para la revisión mensual:

* **se queda**: gana desde que entró al estudio;
* **sale (mueve dinero y pierde)**: pierde desde que entró, con mucho volumen;
* **sale (pierde)**: pierde desde que entró;
* **sin actividad**: no operó en el estudio (tampoco aporta).

Cada consulta se guarda en `data/hft_rendimiento.jsonl` para ver la evolución del mes.
"""
from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

COT = timezone(timedelta(hours=-5))
COHORT = Path("data/hft_cohorte.json")
HISTORY = Path("data/hft_rendimiento.jsonl")
BIG_VOLUME = 50_000_000          # "mueve mucho dinero" en el estudio
WINDOWS = ("day", "week", "month", "allTime")      # de la serie más fina a la más larga


@dataclass
class Rendimiento:
    cuenta: str
    valor: float              # valor de la cuenta (USD)
    semana: float             # ganancia/pérdida de los últimos 7 días
    mes: float                # últimos 30 días
    estudio: float            # desde que entró al estudio
    volumen_semana: float
    volumen_mes: float
    historico: float

    @property
    def por_10k(self) -> float | None:
        """Ganancia por cada $10.000 movidos en el mes (eficiencia). Sin sentido con menos de $1M movido."""
        return self.mes / self.volumen_mes * 10_000 if self.volumen_mes >= 1_000_000 else None

    def veredicto(self, big_volume: float = BIG_VOLUME) -> str:
        if abs(self.estudio) < 1_000 and self.volumen_mes < 1_000_000:
            return "sin actividad"
        if self.estudio > 0:
            return "se queda"
        if self.volumen_mes >= big_volume:
            return "sale (mueve dinero y pierde)"
        return "sale (pierde)"


def cohort(path: Path = COHORT) -> tuple[list[str], str]:
    """Cuentas en estudio y fecha de inicio. Si no hay archivo de cohorte, las del último
    `hft_cuentas_hora.csv` que mandó Juan."""
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return [a.lower() for a in data.get("cuentas", [])], data.get("desde", "")
    files = sorted(Path("data/escucha_pc").glob("*/hft_cuentas_hora.csv"))
    if not files:
        return [], ""
    with files[-1].open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return list(dict.fromkeys(r["cuenta"].lower() for r in rows)), rows[0]["hora_col"][:10] if rows else ""


def pnl_since(portfolio: list, start_ms: int) -> float:
    """Ganancia desde `start_ms`, con la serie más fina que cubra esa fecha."""
    windows = dict(portfolio)
    for name in WINDOWS:
        hist = (windows.get(name) or {}).get("pnlHistory") or []
        if not hist or int(hist[0][0]) > start_ms:
            continue
        before = [float(v) for t, v in hist if int(t) <= start_ms]
        return float(hist[-1][1]) - (before[-1] if before else 0.0)
    hist = (windows.get("allTime") or {}).get("pnlHistory") or []
    return float(hist[-1][1]) - float(hist[0][1]) if hist else 0.0     # la cuenta es más nueva que el estudio


def _window(portfolio: list, name: str) -> tuple[float, float]:
    d = dict(portfolio).get(name) or {}
    hist = d.get("pnlHistory") or []
    pnl = float(hist[-1][1]) - float(hist[0][1]) if hist else 0.0
    return pnl, float(d.get("vlm") or 0)


def from_portfolio(address: str, portfolio: list, start_ms: int) -> Rendimiento:
    week, vw = _window(portfolio, "week")
    month, vm = _window(portfolio, "month")
    hist, _ = _window(portfolio, "allTime")
    av = (dict(portfolio).get("day") or {}).get("accountValueHistory") or []
    return Rendimiento(address, float(av[-1][1]) if av else 0.0, week, month, pnl_since(portfolio, start_ms),
                       vw, vm, hist)


def scan(source, addresses: list[str], desde: str, pause_s: float = 0.2) -> list[Rendimiento]:
    start = datetime.strptime(desde, "%Y-%m-%d").replace(tzinfo=COT) if desde else datetime.now(COT) - timedelta(days=7)
    start_ms = int(start.timestamp() * 1000)
    out = []
    for a in addresses:
        try:
            out.append(from_portfolio(a, source._info({"type": "portfolio", "user": a}), start_ms))
        except Exception:
            continue
        time.sleep(pause_s)
    return sorted(out, key=lambda r: r.estudio, reverse=True)


def save(rows: list[Rendimiento], path: Path = HISTORY) -> None:
    now = datetime.now(COT).strftime("%Y-%m-%d %H:%M")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps({"fecha": now, **{k: round(v) if isinstance(v, float) else v
                                                  for k, v in asdict(r).items()},
                                 "veredicto": r.veredicto()}, ensure_ascii=False) + "\n")


def _usd(v: float) -> str:
    sign = "−" if v < 0 else "+"
    v = abs(v)
    return f"{sign}${v / 1e6:.2f}M" if v >= 1e6 else f"{sign}${v / 1e3:.0f}k"


def report(rows: list[Rendimiento], desde: str, labels: dict[str, str] | None = None) -> list[str]:
    labels = labels or {}
    lines = [f"Cuentas en estudio desde {desde or '?'}: ¿ganan o solo mueven dinero?", "",
             f"{'cuenta':8}  {'tipo':18}  {'estudio':>9}  {'semana':>9}  {'30 días':>9}  {'vol. 30 d':>9}  "
             f"{'por $10k':>8}  veredicto"]
    for r in rows:
        lines.append(f"{r.cuenta[:6]}…  {labels.get(r.cuenta, ''):18}  {_usd(r.estudio):>9}  {_usd(r.semana):>9}  "
                     f"{_usd(r.mes):>9}  {r.volumen_mes / 1e6:8.0f}M  {'—' if r.por_10k is None else f'{r.por_10k:+.1f}':>8}  {r.veredicto()}")
    keep = [r for r in rows if r.veredicto() == "se queda"]
    out = [r for r in rows if r.veredicto().startswith("sale")]
    lines += ["", f"Se quedan {len(keep)} · salen {len(out)} · sin actividad {len(rows) - len(keep) - len(out)}",
              "Regla: una buena ballena es la que gana. Las que mueven dinero y pierden salen en la revisión del mes.",
              "Veredicto provisional hasta la revisión mensual; incluye lo que tienen abierto (no solo lo cerrado)."]
    return lines
