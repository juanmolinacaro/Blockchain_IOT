"""Ejecutor simulado (paper trading): misma interfaz que el real, sin dinero en juego."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..models import AccountState, Order, Position

log = logging.getLogger(__name__)


@dataclass
class PaperExecutor:
    starting_equity: float
    taker_fee: float = 0.00045     # 4.5 bps, tarifa taker base de Hyperliquid
    slippage: float = 0.0005       # 5 bps de deslizamiento adverso
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    trade_log: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.cash = self.starting_equity

    def state(self, mids: dict[str, float]) -> AccountState:
        positions = {}
        upnl_total = 0.0
        for coin, p in self.positions.items():
            px = mids.get(coin, p.entry_px)
            upnl = p.size * (px - p.entry_px)
            upnl_total += upnl
            positions[coin] = Position(coin, p.size, p.entry_px, upnl)
        return AccountState("paper", self.cash + upnl_total, positions)

    def execute(self, order: Order, mid: float, time_ms: int = 0) -> float:
        """Ejecuta a mercado contra `mid` con slippage; devuelve el precio de ejecución."""
        px = mid * (1 + self.slippage) if order.is_buy else mid * (1 - self.slippage)
        signed = order.sz if order.is_buy else -order.sz
        pos = self.positions.get(order.coin)
        cur = pos.size if pos else 0.0
        if order.reduce_only:
            if cur == 0 or (cur > 0) == order.is_buy:
                return px
            signed = max(-abs(cur), min(abs(cur), signed))
        fee = abs(signed) * px * self.taker_fee
        self.cash -= fee
        self.fees_paid += fee

        new = cur + signed
        if cur == 0 or (cur > 0) == (signed > 0):
            entry = (abs(cur) * pos.entry_px + abs(signed) * px) / abs(new) if pos else px
            self.positions[order.coin] = Position(order.coin, new, entry)
        else:
            closed = min(abs(cur), abs(signed))
            pnl = closed * (px - pos.entry_px) * (1 if cur > 0 else -1)
            self.cash += pnl
            self.realized_pnl += pnl
            if abs(new) < 1e-12:
                del self.positions[order.coin]
            elif (new > 0) == (cur > 0):
                self.positions[order.coin] = Position(order.coin, new, pos.entry_px)
            else:  # volteo: el remanente abre al precio actual
                self.positions[order.coin] = Position(order.coin, new, px)
        self.trade_log.append({"time": time_ms, "coin": order.coin, "side": "BUY" if order.is_buy else "SELL",
                               "sz": abs(signed), "px": px, "fee": fee, "reason": order.reason})
        log.info("[PAPER] %s %s %.6g @ %.4f (%s)", "BUY" if order.is_buy else "SELL",
                 order.coin, abs(signed), px, order.reason)
        return px
