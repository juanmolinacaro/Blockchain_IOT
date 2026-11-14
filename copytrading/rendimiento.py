"""Rendimiento de las cuentas en estudio: ¿ganan o solo mueven dinero?

Regla de Juan (7 nov 2026): "una buena ballena es la que gana. No vamos a seguir a una ballena que solo
mueve dinero y pierde: esas son las que van a salir el primer mes". El radar de alta frecuencia mide
CÓMO opera una cuenta (agresiva, mucha rotación); esto mide si GANA. Se descubrió con `0xf71a…`: la
marcamos como "cazador" del barrido del 5 nov y en realidad estaba capitulando; perdió $1,17M esa semana.

Para cada cuenta de la cohorte (`data/hft_cohorte.json`), con el portafolio público de Hyperliquid:
ganancia o pérdida de la semana, de los últimos 30 días y **desde que entró al estudio**, volumen, y
**cuánto gana por cada $10.000 movidos** (eficiencia). Veredicto para la revisión mensual:

* **se queda**: gana desde que entró al estudio;
* **se queda (mala racha: gana en su historial)**: pierde en el estudio, pero en todo su historial en Hyperliquid
  gana más de $1M y al menos $0,5 por cada $10.000 movidos (Juan, 14 nov: "si ya tenemos un historial son más
  datos para decidir"; El Cambista, 0xbf73 y 0x3bca parecían perdedoras en la caída del 4–14 nov y llevan
  +$228M, +$21,6M y +$7,8M en su historial);
* **en observación (gana ahora, pierde en su historial)**: gana en el estudio pero lleva más de $1M perdido en su
  historial (0x7b7f: +$132k en el estudio, −$24,9M en su historial); no entra a la alerta;
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
# Margen de tolerancia de la alerta (acordado con Juan el 7 nov): para ENTRAR, ganar > $100k en el
# estudio; para SALIR, perder la mitad de lo mejor que llegó a ganar o quedar en pérdidas. Así una mala
# racha no saca a una buena cuenta, ni un día de suerte mete a una mala, y no entra y sale por ruido.
ENTER_USD = 100_000              # el pico se mide con cierres diarios, no con los vaivenes de dentro del día
KEEP_FRACTION = 0.5
MIN_ACTIVE_VOLUME = 1_000_000    # tiene que operar de verdad (30 días) para que su empuje cuente
HIST_MIN_USD = 1_000_000         # historial ganador: más de $1M ganado desde que existe la cuenta…
HIST_MIN_PER_10K = 0.5           # …y al menos $0,5 por cada $10.000 movidos (0xf5d8: +$0,3M en $81.200M = 0,04: en cero)


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
    pico: float = 0.0         # lo mejor que llegó a ganar desde que entró al estudio
    volumen_historico: float = 0.0   # todo lo que ha movido desde que existe la cuenta

    @property
    def por_10k(self) -> float | None:
        """Ganancia por cada $10.000 movidos en el mes (eficiencia). Sin sentido con menos de $1M movido."""
        return self.mes / self.volumen_mes * 10_000 if self.volumen_mes >= 1_000_000 else None

    @property
    def por_10k_historico(self) -> float | None:
        """Ganancia por cada $10.000 movidos en TODO su historial."""
        return self.historico / self.volumen_historico * 10_000 if self.volumen_historico >= 10_000_000 else None

    @property
    def gana_historico(self) -> bool:
        e = self.por_10k_historico
        return self.historico >= HIST_MIN_USD and e is not None and e >= HIST_MIN_PER_10K

    @property
    def pierde_historico(self) -> bool:
        return self.historico <= -HIST_MIN_USD

    def veredicto(self, big_volume: float = BIG_VOLUME) -> str:
        if abs(self.estudio) < 1_000 and self.volumen_mes < 1_000_000:
            return "sin actividad"
        if self.estudio > 0:
            return "en observación (gana ahora, pierde en su historial)" if self.pierde_historico else "se queda"
        if self.gana_historico:
            return "se queda (mala racha: gana en su historial)"
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


def pnl_path(portfolio: list, start_ms: int, daily: bool = False) -> list[float]:
    """Ganancia acumulada desde `start_ms` en cada punto, con la serie más fina que cubra esa fecha.
    `daily`: solo el cierre de cada día (hora Colombia) y el valor actual. El pico se mide así: una cuenta
    grande puede subir y bajar millones dentro del mismo día con lo que tiene abierto (0xfc66 llegó a
    +$4,7M a media tarde del 5 nov y cerró el día en +$2,6M); eso es ruido, no lo que "llegó a ganar"."""
    windows = dict(portfolio)
    for name in WINDOWS:
        hist = (windows.get(name) or {}).get("pnlHistory") or []
        if not hist or int(hist[0][0]) > start_ms:
            continue
        before = [float(v) for t, v in hist if int(t) <= start_ms]
        base = before[-1] if before else 0.0
        pts = [(int(t), float(v) - base) for t, v in hist if int(t) >= start_ms] or [(int(hist[-1][0]), float(hist[-1][1]) - base)]
        if daily:
            closes: dict[str, float] = {}
            for t, v in pts:
                closes[datetime.fromtimestamp(t / 1000, COT).strftime("%Y-%m-%d")] = v
            return list(closes.values())
        return [v for _, v in pts]
    hist = (windows.get("allTime") or {}).get("pnlHistory") or []       # la cuenta es más nueva que el estudio
    return [float(v) - float(hist[0][1]) for _, v in hist] if hist else [0.0]


def pnl_since(portfolio: list, start_ms: int) -> float:
    """Ganancia desde `start_ms`."""
    return pnl_path(portfolio, start_ms)[-1]


def _window(portfolio: list, name: str) -> tuple[float, float]:
    d = dict(portfolio).get(name) or {}
    hist = d.get("pnlHistory") or []
    pnl = float(hist[-1][1]) - float(hist[0][1]) if hist else 0.0
    return pnl, float(d.get("vlm") or 0)


def from_portfolio(address: str, portfolio: list, start_ms: int) -> Rendimiento:
    week, vw = _window(portfolio, "week")
    month, vm = _window(portfolio, "month")
    hist, vh = _window(portfolio, "allTime")
    av = (dict(portfolio).get("day") or {}).get("accountValueHistory") or []
    closes = pnl_path(portfolio, start_ms, daily=True)
    return Rendimiento(address, float(av[-1][1]) if av else 0.0, week, month, closes[-1], vw, vm, hist,
                       max(0.0, max(closes)), vh)


def select_winners(rows: list[Rendimiento], previous: set[str] | None = None) -> set[str]:
    """Cuentas que sigue la alerta, con margen de tolerancia: entran al ganar más de ENTER_USD en el
    estudio; las que ya estaban se quedan mientras sigan en ganancia y conserven al menos la mitad de lo
    mejor que llegaron a ganar."""
    previous = previous or set()
    out = set()
    for r in rows:
        healthy = r.estudio > 0 and r.estudio >= KEEP_FRACTION * r.pico     # no perdió la mitad de su pico
        if r.volumen_mes < MIN_ACTIVE_VOLUME or not healthy or r.pierde_historico:   # 14 nov: con historial perdedor, no
            continue
        if r.cuenta in previous or r.estudio > ENTER_USD:
            out.add(r.cuenta)
    return out


def last_winners(path: Path = HISTORY) -> set[str]:
    """Las que seguía la alerta en la última revisión guardada (para no perderlas al reiniciar)."""
    if not path.exists():
        return set()
    last, seen, out = "", set(), set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            if d.get("fecha", "") != last or d["cuenta"] in seen:       # empieza otra revisión
                last, seen, out = d.get("fecha", ""), set(), set()
            seen.add(d["cuenta"])
            if d.get("en_alerta"):
                out.add(d["cuenta"])
    except (OSError, ValueError, KeyError):
        return set()
    return out


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


def save(rows: list[Rendimiento], path: Path = HISTORY, winners: set[str] | None = None) -> None:
    now = datetime.now(COT).strftime("%Y-%m-%d %H:%M")
    winners = winners or set()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps({"fecha": now, **{k: round(v) if isinstance(v, float) else v
                                                  for k, v in asdict(r).items()},
                                 "veredicto": r.veredicto(), "en_alerta": r.cuenta in winners},
                                ensure_ascii=False) + "\n")


def _usd(v: float) -> str:
    sign = "−" if v < 0 else "+"
    v = abs(v)
    return f"{sign}${v / 1e6:.2f}M" if v >= 1e6 else f"{sign}${v / 1e3:.0f}k"


def report(rows: list[Rendimiento], desde: str, labels: dict[str, str] | None = None,
           winners: set[str] | None = None) -> list[str]:
    labels = labels or {}
    winners = winners or set()
    lines = [f"Cuentas en estudio desde {desde or '?'}: ¿ganan o solo mueven dinero?", "",
             f"{'cuenta':8}  {'tipo':18}  {'estudio':>9}  {'semana':>9}  {'30 días':>9}  {'vol. 30 d':>9}  "
             f"{'por $10k':>8}  {'pico':>9}  {'historial':>9}  {'h/$10k':>6}  alerta  veredicto"]
    for r in rows:
        lines.append(f"{r.cuenta[:6]}…  {labels.get(r.cuenta, ''):18}  {_usd(r.estudio):>9}  {_usd(r.semana):>9}  "
                     f"{_usd(r.mes):>9}  {r.volumen_mes / 1e6:8.0f}M  {'—' if r.por_10k is None else f'{r.por_10k:+.1f}':>8}  {_usd(r.pico):>9}  {_usd(r.historico):>9}  {'—' if r.por_10k_historico is None else f'{r.por_10k_historico:+.1f}':>6}  {'💰 sí ' if r.cuenta in winners else '  no  '}  {r.veredicto()}")
    keep = [r for r in rows if r.veredicto().startswith("se queda")]
    out = [r for r in rows if r.veredicto().startswith("sale")]
    obs = [r for r in rows if r.veredicto().startswith("en observación")]
    lines += ["", f"Se quedan {len(keep)} · en observación {len(obs)} · salen {len(out)} · "
                  f"sin actividad {len(rows) - len(keep) - len(out) - len(obs)}",
              f"La alerta 💰 sigue a {len(winners)}: entran al ganar > ${ENTER_USD // 1000}k en el estudio; salen si "
              f"pierden la mitad de su mejor ganancia (pico) o quedan en pérdidas.",
              "Regla: una buena ballena es la que gana. Las que mueven dinero y pierden salen en la revisión del mes.",
              "Con historial (14 nov): una mala racha no saca a una cuenta que gana en todo su historial, y una buena "
              "racha no mete a la alerta a una que pierde en su historial.",
              "Veredicto provisional hasta la revisión mensual; incluye lo que tienen abierto (no solo lo cerrado)."]
    return lines
