"""¿La bolsa o la disculpa? Compara cada movimiento fuerte de BTC con el Nasdaq.

Idea de Juan (6 nov 2026): "siempre que hay una caída le echan la culpa a las noticias, pero parece más una
disculpa" (la del 5 nov la achacaron al desplome de las tecnológicas). Para medirlo:

1. Se buscan los movimientos fuertes de BTC en los datos de la escucha: al menos `umbral` (1,5 %) en
   menos de `ventana` (60) minutos, contados desde el máximo (caída) o el mínimo (subida) previo.
2. Para cada uno se mira el Nasdaq 100 (futuro NQ) en los `antes` (30) minutos previos y durante.
3. Se clasifica:
   * **la bolsa se movió primero**: el Nasdaq ya iba en la misma dirección al menos `nq_antes` (0,3 %)
     antes de que BTC arrancara;
   * **a la vez**: el Nasdaq se movió al menos `nq_durante` (0,4 %) en la misma dirección mientras BTC caía;
   * **solo cripto**: el Nasdaq no acompañó; si culpan a la bolsa, es disculpa;
   * **bolsa sin datos**: el futuro no cotizaba (fin de semana, pausa diaria) o faltan datos.

Los umbrales son un punto de partida; con un mes de datos se revisan.
"""
from __future__ import annotations

import csv
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

COT = timezone(timedelta(hours=-5))
BTC_FILES = (Path("data/hft_flujo.csv"), Path("data/binance_minuto.csv"))
NQ_FILE = Path("data/nasdaq_minuto.csv")
Series = list[tuple[datetime, float]]


@dataclass
class Episodio:
    inicio: datetime
    fin: datetime
    btc_inicio: float
    btc_fin: float
    nq_antes: float | None       # cambio del Nasdaq en los minutos previos (fracción)
    nq_durante: float | None
    bolsa_abierta: bool          # sesión normal de Nueva York (9:30–16:00 hora de Nueva York)
    causa: str
    inicio_sin_grabar: bool = False   # justo antes no hay datos: el movimiento pudo empezar antes

    @property
    def btc_cambio(self) -> float:
        return self.btc_fin / self.btc_inicio - 1

    @property
    def minutos(self) -> int:
        return int((self.fin - self.inicio).total_seconds() // 60)


def _when(s: str) -> datetime:
    return datetime.strptime(s.strip()[:16].replace("T", " "), "%Y-%m-%d %H:%M").replace(tzinfo=COT)


def read_series(path: Path, key: str, value: str, price_col: str = "precio") -> Series:
    """Serie (hora, precio) de un CSV de la escucha, una fila por minuto, sin duplicados."""
    if not path.exists():
        return []
    out: dict[datetime, float] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get(key) != value:
                continue
            try:
                px = float(row[price_col])
                if px > 0:
                    out[_when(row["hora_col"])] = px
            except (KeyError, ValueError):
                continue
    return sorted(out.items())


def btc_series(files=BTC_FILES) -> Series:
    """BTC por minuto: Hyperliquid (escucha) y, donde falte, Binance."""
    merged: dict[datetime, float] = {}
    for path in reversed(files):              # el primero de la lista manda
        merged.update(dict(read_series(path, "moneda", "BTC")))
    return sorted(merged.items())


def _ny_offset(d: datetime) -> int:
    """Horas de Nueva York respecto a UTC (−4 en horario de verano, −5 en invierno)."""
    y = d.year
    march = datetime(y, 3, 8, tzinfo=timezone.utc)
    start = march + timedelta(days=(6 - march.weekday()) % 7, hours=7)      # 2.º domingo de marzo, 2:00 NY
    nov = datetime(y, 11, 1, tzinfo=timezone.utc)
    end = nov + timedelta(days=(6 - nov.weekday()) % 7, hours=6)            # 1.er domingo de noviembre, 2:00 NY
    return -4 if start <= d.astimezone(timezone.utc) < end else -5


def bolsa_abierta(d: datetime) -> bool:
    ny = d.astimezone(timezone(timedelta(hours=_ny_offset(d))))
    if ny.weekday() >= 5:
        return False
    minutes = ny.hour * 60 + ny.minute
    return 9 * 60 + 30 <= minutes < 16 * 60


def _price_at(series: Series, times: list[datetime], t: datetime, tol_min: int = 5) -> float | None:
    """Último precio conocido en `t` (con hasta `tol_min` minutos de antigüedad)."""
    i = bisect_right(times, t) - 1
    if i < 0 or (t - times[i]) > timedelta(minutes=tol_min):
        return None
    return series[i][1]


def find_moves(btc: Series, umbral: float = 0.015, ventana: int = 60) -> list[tuple[int, int]]:
    """Movimientos de al menos `umbral` en menos de `ventana` minutos: pares (índice inicio, índice fin)."""
    moves, i, n = [], 0, len(btc)
    while i < n - 1:
        t0, p0 = btc[i]
        j, lo_j, hi_j = i + 1, i, i
        while j < n and btc[j][0] - t0 <= timedelta(minutes=ventana):
            if btc[j][1] < btc[lo_j][1]:
                lo_j = j
            if btc[j][1] > btc[hi_j][1]:
                hi_j = j
            j += 1
        # caída desde el máximo del tramo hasta el mínimo posterior, o subida desde el mínimo
        found = None
        if lo_j > i and btc[lo_j][1] / p0 - 1 <= -umbral and all(btc[k][1] <= p0 for k in range(i, lo_j + 1)):
            found = lo_j
        elif hi_j > i and btc[hi_j][1] / p0 - 1 >= umbral and all(btc[k][1] >= p0 for k in range(i, hi_j + 1)):
            found = hi_j
        if found is None:
            i += 1
            continue
        # alargar mientras siga en la misma dirección sin rebotar más de la mitad del umbral
        down = btc[found][1] < p0
        k = found + 1
        while k < n and btc[k][0] - btc[found][0] <= timedelta(minutes=ventana):
            better = btc[k][1] < btc[found][1] if down else btc[k][1] > btc[found][1]
            if better:
                found = k
            elif abs(btc[k][1] / btc[found][1] - 1) > umbral / 2:
                break
            k += 1
        # el movimiento arranca en la última vez que estuvo en el máximo (o mínimo), no al inicio del techo plano
        start = max(k for k in range(i, found) if btc[k][1] == p0)
        moves.append((start, found))
        i = found + 1
    return moves


def classify(nq_antes: float | None, nq_durante: float | None, down: bool,
             lim_antes: float = 0.003, lim_durante: float = 0.004) -> str:
    if nq_antes is None or nq_durante is None:
        return "bolsa sin datos"
    sign = -1 if down else 1
    if sign * nq_antes >= lim_antes:
        return "la bolsa se movió primero"
    if sign * nq_durante >= lim_durante:
        return "a la vez"
    return "solo cripto"


def episodes(btc: Series, nq: Series, umbral: float = 0.015, ventana: int = 60, antes: int = 30) -> list[Episodio]:
    times = [t for t, _ in nq]
    out = []
    for i, j in find_moves(btc, umbral, ventana):
        (t0, p0), (t1, p1) = btc[i], btc[j]
        a = _price_at(nq, times, t0 - timedelta(minutes=antes))
        b = _price_at(nq, times, t0)
        c = _price_at(nq, times, t1)
        nq_antes = b / a - 1 if a and b else None
        nq_durante = c / b - 1 if b and c else None
        gap = i == 0 or t0 - btc[i - 1][0] > timedelta(minutes=5)
        out.append(Episodio(t0, t1, p0, p1, nq_antes, nq_durante, bolsa_abierta(t0),
                            classify(nq_antes, nq_durante, p1 < p0), gap))
    return out


def _pct(v: float | None) -> str:
    return "  sin dato" if v is None else f"{v * 100:+8.2f} %"


def report(eps: list[Episodio]) -> list[str]:
    if not eps:
        return ["Sin movimientos fuertes de BTC en los datos guardados (o faltan los archivos de la escucha)."]
    lines = [f"{'inicio (Colombia)':17}  {'min':>4}  {'BTC':>9}  {'Nasdaq antes':>12}  {'Nasdaq durante':>14}  "
             f"bolsa NY  causa"]
    for e in eps:
        lines.append(f"{e.inicio:%Y-%m-%d %H:%M}  {e.minutos:4d}  {e.btc_cambio * 100:+8.2f} %  {_pct(e.nq_antes):>12}  "
                     f"{_pct(e.nq_durante):>14}  {'abierta ' if e.bolsa_abierta else 'cerrada '}  {e.causa}"
                     + ("  (empezó antes de grabar: el inicio real se desconoce)" if e.inicio_sin_grabar else ""))
    medidos = [e for e in eps if e.causa != "bolsa sin datos"]
    lines.append("")
    lines.append(f"{len(eps)} movimientos fuertes · {len(medidos)} con datos del Nasdaq")
    for causa in ("la bolsa se movió primero", "a la vez", "solo cripto"):
        n = sum(e.causa == causa for e in medidos)
        if medidos:
            lines.append(f"  {causa:26} {n:3d}  ({n / len(medidos) * 100:.0f} %)")
    if len(medidos) < 20:
        lines.append("Todavía son pocos casos: el resultado cambia mucho con cada movimiento nuevo.")
    return lines
