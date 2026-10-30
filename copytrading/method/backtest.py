"""Backtest del método canales + absorción de liquidez (docs/METODO_CANALES_LIQUIDEZ.md).

Reglas (evaluadas al CIERRE de cada vela, sin mirar el futuro):

LARGO
  1. Toque: el mínimo de la vela llega a la parte baja del canal.
  2. Absorción: en esa vela se barrió liquidez de longs (estimada) por al menos
     `min_sweep` veces el volumen medio por vela.
  3. Recuperación: la vela cierra de nuevo dentro del canal (por encima del borde inferior).
  -> Entrada al cierre. Stop bajo el mínimo de la vela. TP1 = centro del canal
     (se cierra la mitad y el stop pasa a la entrada). TP2 = borde superior.

CORTO: simétrico en la parte alta del canal con liquidez de shorts.

Variante "objetivo" (entry="target"): rechazo en el borde del canal (toca y cierra
dentro) cuando hay más liquidez al otro lado; TP2 = la zona de liquidez más cargada
en esa dirección ("el precio va a buscar la liquidez").

Stop: por mecha ("wick") o por cierre ("close", como pide el método: solo se sale
si una vela CIERRA más allá del stop; con un stop de emergencia a `hard_stop_r` R).

Para saber si la liquidez aporta ventaja de verdad, se compara con "solo canal"
(las mismas reglas sin la condición de absorción).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..models import Candle
from .channels import regression_channel
from .liqmodel import LiquidationModel


@dataclass
class MethodConfig:
    lookback: int = 60              # velas para trazar el canal
    channel_q: float = 0.9
    touch_tol: float = 0.002        # el mínimo puede quedarse a 0.2 % del borde
    min_sweep: float = 1.5          # liquidez absorbida / volumen medio por vela
    use_liquidity: bool = True      # False = "solo canal" (comparación)
    entry: str = "sweep"            # "sweep": rebote tras absorción | "target": ir a por la liquidez
    stop_mode: str = "wick"         # "wick" | "close"
    hard_stop_r: float = 2.0        # en modo "close", salida de emergencia si la mecha llega a 2R
    imbalance: float = 1.5          # entry="target": liquidez a favor / en contra mínima
    liq_range: float = 0.08         # zona de búsqueda de liquidez: ±8 % del precio
    trend: str = "none"             # "none" | "channel": solo largos si el canal sube, cortos si baja
    sides: str = "both"             # "both" | "long" | "short"
    stop_buffer: float = 0.001      # stop 0.1 % más allá del extremo de la vela
    min_rr: float = 1.0             # beneficio/riesgo mínimo hasta TP2
    max_bars: int = 30              # cierre por tiempo
    fee: float = 0.00045            # comisión por lado (taker Hyperliquid)
    slippage: float = 0.0003
    risk_per_trade: float = 0.01    # 1 % del capital por operación
    half_life_bars: float = 84      # vida media de los niveles de liquidación (84 velas de 4h = 14 días)
    vol_window: int = 50


@dataclass
class Trade:
    side: str
    entry_i: int
    entry: float
    stop: float
    tp1: float
    tp2: float
    exit_i: int = -1
    r: float = 0.0            # resultado en múltiplos de R, neto de costes
    exit_reason: str = ""


@dataclass
class Result:
    trades: list[Trade] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        return sum(t.r > 0 for t in self.trades) / self.n if self.n else 0.0

    @property
    def expectancy(self) -> float:
        return sum(t.r for t in self.trades) / self.n if self.n else 0.0

    @property
    def profit_factor(self) -> float:
        g = sum(t.r for t in self.trades if t.r > 0)
        l = -sum(t.r for t in self.trades if t.r < 0)
        return g / l if l else (math.inf if g else 0.0)

    @property
    def total_return(self) -> float:
        return self.equity[-1] / self.equity[0] - 1 if self.equity else 0.0

    @property
    def max_drawdown(self) -> float:
        peak, worst = -math.inf, 0.0
        for e in self.equity:
            peak = max(peak, e)
            worst = max(worst, (peak - e) / peak)
        return worst


@dataclass(frozen=True)
class LiqSnapshot:
    sweep_long: float      # longs absorbidos en la vela / volumen medio por vela
    sweep_short: float
    long_below: float      # liquidez de longs por debajo (dentro de liq_range) / volumen medio
    short_above: float
    best_long_px: float    # nivel de longs más cargado por debajo (0 si no hay)
    best_short_px: float


def compute_liquidity(candles: list[Candle], cfg: MethodConfig) -> list[LiqSnapshot]:
    """Estado del mapa de liquidaciones estimado al cierre de cada vela (no depende del canal)."""
    model = LiquidationModel(decay_per_bar=0.5 ** (1 / cfg.half_life_bars))
    out, usd_hist = [], []
    for c in candles:
        sl, ss = model.update(c)
        usd_hist.append(c.v * c.c)
        window = usd_hist[-cfg.vol_window:]
        avg = sum(window) / len(window) or 1.0
        lo_b, hi_b = model._bin(c.c * (1 - cfg.liq_range)), model._bin(c.c * (1 + cfg.liq_range))
        longs = {b: v for b, v in model.longs.items() if b >= lo_b}
        shorts = {b: v for b, v in model.shorts.items() if b <= hi_b}
        bl = max(longs, key=longs.get) if longs else None
        bs = max(shorts, key=shorts.get) if shorts else None
        out.append(LiqSnapshot(sl / avg, ss / avg, sum(longs.values()) / avg, sum(shorts.values()) / avg,
                               model.price_of(bl) if bl is not None else 0.0,
                               model.price_of(bs) if bs is not None else 0.0))
    return out


def find_signal(candles: list[Candle], i: int, cfg: MethodConfig,
                liq: list[LiqSnapshot]) -> Trade | None:
    ch = regression_channel(candles, i, cfg.lookback, cfg.channel_q)
    if ch is None:
        return None
    c = candles[i]
    lower, upper, mid = ch.lower(i), ch.upper(i), ch.mid(i)
    slope = ch.slope_pct(i)
    s = liq[i]

    if cfg.sides in ("both", "long") and (cfg.trend == "none" or slope > 0):
        touched = c.l <= lower * (1 + cfg.touch_tol)
        if cfg.entry == "sweep":
            ok = not cfg.use_liquidity or s.sweep_long >= cfg.min_sweep
            tp2 = upper
        else:  # "target": hay más shorts arriba que longs abajo -> el precio irá a por ellos
            ok = not cfg.use_liquidity or (s.short_above >= cfg.imbalance * s.long_below
                                           and s.best_short_px > mid)
            tp2 = s.best_short_px if cfg.use_liquidity else upper
        if touched and ok and c.c > lower:
            entry = c.c * (1 + cfg.slippage)
            stop = c.l * (1 - cfg.stop_buffer)
            if mid > entry and (tp2 - entry) >= cfg.min_rr * (entry - stop) > 0:
                return Trade("long", i, entry, stop, mid, tp2)

    if cfg.sides in ("both", "short") and (cfg.trend == "none" or slope < 0):
        touched = c.h >= upper * (1 - cfg.touch_tol)
        if cfg.entry == "sweep":
            ok = not cfg.use_liquidity or s.sweep_short >= cfg.min_sweep
            tp2 = lower
        else:
            ok = not cfg.use_liquidity or (s.long_below >= cfg.imbalance * s.short_above
                                           and 0 < s.best_long_px < mid)
            tp2 = s.best_long_px if cfg.use_liquidity else lower
        if touched and ok and c.c < upper:
            entry = c.c * (1 - cfg.slippage)
            stop = c.h * (1 + cfg.stop_buffer)
            if mid < entry and (entry - tp2) >= cfg.min_rr * (stop - entry) > 0:
                return Trade("short", i, entry, stop, mid, tp2)
    return None


def manage(trade: Trade, candles: list[Candle], cfg: MethodConfig) -> Trade:
    """Simula la operación vela a vela. Si stop y objetivo caen en la misma vela, se asume el stop (conservador)."""
    long = trade.side == "long"
    risk = abs(trade.entry - trade.stop)
    sign = 1 if long else -1
    stop, half_done, realized = trade.stop, False, 0.0
    cost_r = 2 * cfg.fee * trade.entry / risk          # comisiones de entrada + salida, en R

    def r_at(px: float) -> float:
        return sign * (px - trade.entry) / risk

    last = min(trade.entry_i + cfg.max_bars, len(candles) - 1)
    for j in range(trade.entry_i + 1, last + 1):
        c = candles[j]
        if cfg.stop_mode == "close" and not half_done:
            hard = trade.entry - sign * cfg.hard_stop_r * risk
            if c.l <= hard if long else c.h >= hard:          # emergencia: la mecha llegó a hard_stop_r
                hit_stop, stop_px = True, hard
            else:
                hit_stop, stop_px = (c.c <= stop if long else c.c >= stop), c.c
        else:
            hit_stop, stop_px = (c.l <= stop if long else c.h >= stop), stop
        if hit_stop:
            px = stop_px * (1 - cfg.slippage) if long else stop_px * (1 + cfg.slippage)
            realized += (0.5 if half_done else 1.0) * r_at(px)
            trade.exit_i, trade.exit_reason = j, "stop" if not half_done else "breakeven"
            break
        if not half_done and (c.h >= trade.tp1 if long else c.l <= trade.tp1):
            realized += 0.5 * r_at(trade.tp1)
            half_done, stop = True, trade.entry
        if half_done and (c.h >= trade.tp2 if long else c.l <= trade.tp2):
            realized += 0.5 * r_at(trade.tp2)
            trade.exit_i, trade.exit_reason = j, "tp2"
            break
    else:
        px = candles[last].c
        realized += (0.5 if half_done else 1.0) * r_at(px)
        trade.exit_i, trade.exit_reason = last, "tiempo"
    trade.r = realized - cost_r
    return trade


def run(candles: list[Candle], cfg: MethodConfig, start: int = 0, end: int | None = None,
        liq: list[LiqSnapshot] | None = None) -> Result:
    """Una sola operación abierta a la vez; riesgo fijo por operación con interés compuesto."""
    end = len(candles) if end is None else end
    liq = liq or compute_liquidity(candles, cfg)
    res = Result(equity=[1.0])
    i = max(start, cfg.lookback)
    while i < end - 1:
        trade = find_signal(candles, i, cfg, liq)
        if trade is None:
            i += 1
            continue
        manage(trade, candles, cfg)
        res.trades.append(trade)
        res.equity.append(res.equity[-1] * (1 + cfg.risk_per_trade * trade.r))
        i = trade.exit_i + 1
    return res
