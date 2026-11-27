"""Descubrimiento y puntuación de traders rentables a partir de su historial on-chain.

Idea central: el PnL del leaderboard no basta. Hay que separar habilidad
consistente de suerte, apalancamiento extremo o actividad que no se puede
replicar (market making, HFT, arbitraje).
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .config import ScoringConfig
from .models import Fill, LeaderboardEntry, TraderStats

MS_PER_DAY = 86_400_000


@dataclass(frozen=True)
class RoundTrip:
    """Ciclo de vida completo de una posición: desde 0 hasta volver a 0 (o voltearse)."""

    coin: str
    open_time: int
    close_time: int
    pnl: float  # neto de comisiones

    @property
    def hold_minutes(self) -> float:
        return (self.close_time - self.open_time) / 60_000


def round_trips(fills: list[Fill]) -> list[RoundTrip]:
    """Agrupa fills en operaciones completas por moneda."""
    trips: list[RoundTrip] = []
    open_state: dict[str, tuple[int, float]] = {}  # coin -> (open_time, pnl acumulado)
    for f in sorted(fills, key=lambda f: f.time):
        opened_at, acc = open_state.get(f.coin, (f.time, 0.0))
        acc += f.closed_pnl - f.fee
        start, end = f.start_position, f.end_position
        crossed_zero = start != 0 and (end == 0 or (start > 0) != (end > 0))
        if crossed_zero:
            trips.append(RoundTrip(f.coin, opened_at, f.time, acc))
            if end != 0:  # flip: se abre una nueva posición en sentido contrario
                open_state[f.coin] = (f.time, 0.0)
            else:
                open_state.pop(f.coin, None)
        else:
            open_state[f.coin] = (opened_at, acc)
    return trips


def daily_pnl(fills: list[Fill], start_ms: int, end_ms: int) -> list[float]:
    """PnL realizado neto por día UTC, incluyendo los días sin actividad."""
    first_day, last_day = start_ms // MS_PER_DAY, end_ms // MS_PER_DAY
    days = [0.0] * (last_day - first_day + 1)
    for f in fills:
        idx = f.time // MS_PER_DAY - first_day
        if 0 <= idx < len(days):
            days[idx] += f.closed_pnl - f.fee
    return days


def max_drawdown(start_equity: float, pnl_series: list[float]) -> float:
    equity = peak = max(start_equity, 1e-9)
    worst = 0.0
    for p in pnl_series:
        equity += p
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
    return worst


def compute_stats(address: str, fills: list[Fill], account_value: float,
                  start_ms: int, end_ms: int) -> TraderStats:
    stats = TraderStats(address=address, account_value=account_value)
    trips = round_trips(fills)
    stats.n_trades = len(trips)
    stats.total_fees = sum(f.fee for f in fills)
    stats.total_pnl = sum(f.closed_pnl for f in fills) - stats.total_fees
    if fills:
        stats.days_since_last_trade = (end_ms - fills[-1].time) / MS_PER_DAY
        stats.active_days = len({f.time // MS_PER_DAY for f in fills})
        span_days = max((end_ms - fills[0].time) / MS_PER_DAY, 1.0)
        stats.trades_per_day = stats.n_trades / span_days
    if not trips:
        return stats

    wins = [t.pnl for t in trips if t.pnl > 0]
    losses = [-t.pnl for t in trips if t.pnl < 0]
    stats.win_rate = len(wins) / len(trips)
    stats.profit_factor = sum(wins) / sum(losses) if losses else (math.inf if wins else 0.0)
    stats.avg_hold_minutes = statistics.fmean(t.hold_minutes for t in trips)
    stats.top_trade_share = max(wins) / sum(wins) if wins else 1.0

    days = daily_pnl(fills, start_ms, end_ms)
    if len(days) > 1 and statistics.pstdev(days) > 0:
        stats.sharpe = statistics.fmean(days) / statistics.pstdev(days) * math.sqrt(365)
    start_equity = account_value - stats.total_pnl
    stats.max_drawdown = max_drawdown(start_equity, days)
    return stats


def apply_filters(stats: TraderStats, cfg: ScoringConfig) -> TraderStats:
    checks = [
        (stats.n_trades >= cfg.min_trades, f"pocos trades ({stats.n_trades})"),
        (stats.active_days >= cfg.min_active_days, f"pocos días activos ({stats.active_days})"),
        (stats.account_value >= cfg.min_account_value, f"cuenta pequeña (${stats.account_value:,.0f})"),
        (stats.total_pnl > 0, "PnL neto negativo"),
        (stats.win_rate >= cfg.min_win_rate, f"win rate bajo ({stats.win_rate:.0%})"),
        (stats.profit_factor >= cfg.min_profit_factor, f"profit factor bajo ({stats.profit_factor:.2f})"),
        (stats.max_drawdown <= cfg.max_drawdown, f"drawdown alto ({stats.max_drawdown:.0%})"),
        (stats.top_trade_share <= cfg.max_top_trade_share,
         f"PnL concentrado en un trade ({stats.top_trade_share:.0%})"),
        (stats.avg_hold_minutes >= cfg.min_avg_hold_minutes,
         f"demasiado rápido para copiar ({stats.avg_hold_minutes:.1f} min)"),
        (stats.trades_per_day <= cfg.max_trades_per_day,
         f"posible bot/market maker ({stats.trades_per_day:.0f} trades/día)"),
        (stats.days_since_last_trade <= cfg.max_days_since_last_trade,
         f"inactivo ({stats.days_since_last_trade:.0f} días)"),
    ]
    stats.rejected_reasons = [reason for ok, reason in checks if not ok]
    return stats


def _norm(x: float, lo: float, hi: float) -> float:
    if math.isinf(x):
        return 1.0 if x > 0 else 0.0
    return min(max((x - lo) / (hi - lo), 0.0), 1.0)


def score(stats: TraderStats, cfg: ScoringConfig) -> float:
    """Puntuación compuesta en [0, 1]. Prioriza consistencia (Sharpe) sobre PnL bruto."""
    base_equity = max(stats.account_value - stats.total_pnl, 1.0)
    roi = stats.total_pnl / base_equity
    stats.score = (
        0.35 * _norm(stats.sharpe, 0.0, 4.0)
        + 0.20 * _norm(stats.profit_factor, 1.0, 3.0)
        + 0.15 * stats.win_rate
        + 0.15 * (1.0 - _norm(stats.max_drawdown, 0.0, cfg.max_drawdown))
        + 0.15 * _norm(roi, 0.0, 1.0)
    )
    return stats.score


def prefilter_leaderboard(rows: list[LeaderboardEntry], cfg: ScoringConfig,
                          top_n: int = 50) -> list[LeaderboardEntry]:
    """Filtro barato sobre el leaderboard antes de descargar fills de cada wallet."""
    candidates = [
        r for r in rows
        if r.account_value >= cfg.min_account_value
        and r.pnl.get("month", 0) > 0
        and r.pnl.get("allTime", 0) > 0
        and r.pnl.get("week", 0) > -0.1 * r.account_value
        # volumen mensual > 200x la cuenta suele indicar market making / HFT
        and r.volume.get("month", 0) < 200 * r.account_value
    ]
    candidates.sort(key=lambda r: r.roi.get("month", 0), reverse=True)
    return candidates[:top_n]
