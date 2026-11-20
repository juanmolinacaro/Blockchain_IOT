"""Cuentas candidatas para la revisión mensual de la cohorte (acordado con Juan, 20 nov 2026).

La cohorte del 4 nov salió de las cuentas MÁS ACTIVAS (robots de alta frecuencia): de 30, solo 2 ganan (El
Cambista y El Paciente). Regla de Juan: "una buena ballena es la que gana". Las candidatas salen del ranking de
Hyperliquid por lo que GANAN, con todos estos filtros:

* historial ≥ $5M ganado y ≥ $0,5 por cada $10.000 movidos (eficiencia, como El Paciente: +8,4);
* el último mes en ganancia (≥ $500k), para no meter a una que ya dejó de funcionar;
* operan de verdad: ≥ $1.000M movidos en el mes (si no, no hay empuje que seguir);
* cuenta de al menos $1M.

Se ordenan por eficiencia del mes (ganancia por cada $10.000 movidos). El ranking suma las subcuentas: para cada
candidata se dice cuántas tiene, porque la escucha ve las operaciones de cada dirección por separado (si gana con
sus subcuentas, hay que seguir también esas). Las que entren a la cohorte empiezan EN OBSERVACIÓN: no dan señales
hasta demostrar que se adelantan al precio (como El Paciente: 12 de 15 a 4 h).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

OUT = Path("data/candidatas.json")
MIN_HIST = 5_000_000
MIN_MONTH = 500_000
MIN_MONTH_VOL = 1_000_000_000
MIN_EFF_HIST = 0.5            # $ por cada $10.000 movidos
MIN_VALUE = 1_000_000


def eff(pnl: float, vol: float) -> float | None:
    return pnl / vol * 10_000 if vol >= 10_000_000 else None


def select(board: list, exclude: set[str], n: int = 25) -> list[dict]:
    out = []
    for e in board:
        a = e.address.lower()
        if a in exclude:
            continue
        hist, month = e.pnl.get("allTime", 0.0), e.pnl.get("month", 0.0)
        vh, vm = e.volume.get("allTime", 0.0), e.volume.get("month", 0.0)
        eh, em = eff(hist, vh), eff(month, vm)
        if (hist < MIN_HIST or month < MIN_MONTH or vm < MIN_MONTH_VOL or e.account_value < MIN_VALUE
                or eh is None or eh < MIN_EFF_HIST or em is None):
            continue
        out.append({"cuenta": a, "valor": round(e.account_value), "mes": round(month), "historial": round(hist),
                    "semana": round(e.pnl.get("week", 0.0)), "vol_mes": round(vm), "ef_mes": round(em, 2),
                    "ef_historial": round(eh, 2)})
    out.sort(key=lambda r: (-r["ef_mes"], -r["historial"]))
    return out[:n]


def add_subaccounts(source, rows: list[dict]) -> None:
    for r in rows:
        try:
            r["subcuentas"] = len(source._info({"type": "subAccounts", "user": r["cuenta"]}) or [])
        except Exception:
            r["subcuentas"] = None


def save(rows: list[dict], path: Path = OUT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "criterios": {"historial_min": MIN_HIST, "mes_min": MIN_MONTH, "vol_mes_min": MIN_MONTH_VOL,
                                              "eficiencia_historial_min": MIN_EFF_HIST, "valor_min": MIN_VALUE},
                                "candidatas": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


def report(rows: list[dict]) -> list[str]:
    lines = [f"{'#':>2} {'cuenta':8} {'valor':>8} {'mes':>8} {'semana':>8} {'historial':>9} {'vol mes':>8} "
             f"{'ef. mes':>7} {'ef. hist':>8} {'subcuentas':>10}"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i:2} {r['cuenta'][:6]}…  ${r['valor'] / 1e6:6.1f}M {r['mes'] / 1e6:+7.1f}M {r['semana'] / 1e6:+7.1f}M "
                     f"{r['historial'] / 1e6:+8.1f}M {r['vol_mes'] / 1e9:6.1f}B {r['ef_mes']:+7.1f} {r['ef_historial']:+8.1f} "
                     f"{'?' if r.get('subcuentas') is None else r['subcuentas']:>10}")
    lines += ["", "ef. = ganancia por cada $10.000 movidos. Entran en observación: sin señales hasta medirlas."]
    return lines
