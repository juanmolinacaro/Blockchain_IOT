"""Backtest de copia: ¿cuánto habría ganado YO copiando a este líder?

Se reproduce el historial de fills del líder con:
  * retraso (latencia de detección + envío de orden), modelado como deslizamiento extra,
  * comisiones taker y deslizamiento propio,
  * los mismos límites de riesgo que en vivo (tamaño máximo por moneda, orden mínima).

La métrica clave es el *capture ratio*: qué fracción del rendimiento del
líder sobrevive a la copia. Si es baja, el líder no es copiable aunque gane.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .config import RiskConfig
from .execution.paper import PaperExecutor
from .models import Fill, Order
from .replicator import round_size
from .scoring import max_drawdown

PriceFn = Callable[[str, int], float | None]


@dataclass
class BacktestResult:
    leader: str
    start_equity: float
    end_equity: float
    leader_return: float
    n_orders: int
    fees: float
    max_drawdown: float
    equity_curve: list[tuple[int, float]] = field(default_factory=list)

    @property
    def total_return(self) -> float:
        return self.end_equity / self.start_equity - 1

    @property
    def capture_ratio(self) -> float:
        return self.total_return / self.leader_return if self.leader_return else 0.0

    def summary(self) -> str:
        return (f"Líder {self.leader}\n"
                f"  Rentabilidad líder:  {self.leader_return:+.2%}\n"
                f"  Rentabilidad copia:  {self.total_return:+.2%}  (capture ratio {self.capture_ratio:.2f})\n"
                f"  Equity final:        ${self.end_equity:,.2f} (inicio ${self.start_equity:,.2f})\n"
                f"  Órdenes: {self.n_orders} | Comisiones: ${self.fees:,.2f} | Max DD: {self.max_drawdown:.2%}")


def run_backtest(leader: str, fills: list[Fill], leader_equity_now: float, risk: RiskConfig,
                 latency_ms: int = 3_000, latency_slippage_bps: float = 5.0,
                 sz_decimals: dict[str, int] | None = None,
                 price_fn: PriceFn | None = None) -> BacktestResult:
    """
    price_fn(coin, t_ms) -> precio real en t (p. ej. desde velas de 1m). Si no se da,
    se usa el precio del fill del líder empeorado en `latency_slippage_bps`.
    """
    fills = sorted(fills, key=lambda f: f.time)
    sz_decimals = sz_decimals or {}
    executor = PaperExecutor(risk.my_equity, slippage=0.0)  # el deslizamiento va en px

    # equity del líder en cada momento ≈ equity actual - PnL realizado posterior
    net = [f.closed_pnl - f.fee for f in fills]
    total_net = sum(net)
    leader_start = max(leader_equity_now - total_net, 1e-9)
    leader_eq = leader_start

    skipped: set[str] = set()      # posiciones abiertas antes del inicio de la ventana
    seen: set[str] = set()
    last_px: dict[str, float] = {}
    curve: list[tuple[int, float]] = []

    for f, pnl in zip(fills, net):
        if f.coin not in seen:
            seen.add(f.coin)
            if f.start_position != 0 and not risk.copy_existing_positions:
                skipped.add(f.coin)
        if f.coin in skipped:
            if f.end_position == 0 or (f.end_position > 0) != (f.start_position > 0):
                skipped.discard(f.coin)  # el líder cerró la posición heredada
                if f.end_position == 0:
                    leader_eq += pnl
                    continue
            else:
                leader_eq += pnl
                continue

        exec_time = f.time + latency_ms
        px = price_fn(f.coin, exec_time) if price_fn else None
        if px is None:
            adverse = latency_slippage_bps / 10_000
            px = f.px * (1 + adverse) if f.side == "B" else f.px * (1 - adverse)
        last_px[f.coin] = px

        my_eq = executor.state(last_px).equity
        target = f.end_position * (my_eq / leader_eq) * risk.size_multiplier
        cap = risk.max_position_pct * my_eq / px
        target = max(-cap, min(cap, target))
        target = round_size(target, sz_decimals.get(f.coin, 4))

        cur_pos = executor.positions.get(f.coin)
        cur = cur_pos.size if cur_pos else 0.0
        delta = target - cur
        if delta != 0 and (target == 0 or abs(delta) * px >= risk.min_order_usd):
            reduce_only = abs(target) < abs(cur) and (target == 0 or (target > 0) == (cur > 0))
            # un volteo (long -> short) va en una sola orden; PaperExecutor lo gestiona
            executor.execute(Order(f.coin, delta > 0, abs(delta), reduce_only=reduce_only), px, exec_time)

        leader_eq += pnl
        curve.append((exec_time, executor.state(last_px).equity))

    end_eq = executor.state(last_px).equity
    pnl_steps = [b - a for (_, a), (_, b) in zip([(0, risk.my_equity)] + curve[:-1], curve)]
    return BacktestResult(
        leader=leader,
        start_equity=risk.my_equity,
        end_equity=end_eq,
        leader_return=total_net / leader_start,
        n_orders=len(executor.trade_log),
        fees=executor.fees_paid,
        max_drawdown=max_drawdown(risk.my_equity, pnl_steps),
        equity_curve=curve,
    )
