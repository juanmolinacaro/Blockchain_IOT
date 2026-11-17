"""Motor de replicación: convierte las posiciones de los líderes en órdenes propias.

Se replica el *estado* (posición objetivo) en lugar de cada fill individual.
Así, si se pierde un evento o el líder entra en varias partes, el sistema
converge igualmente a la posición correcta, y las salidas del líder
(posición -> 0) se traducen automáticamente en cierres propios.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .config import LeaderConfig, RiskConfig
from .models import AccountState, Order

log = logging.getLogger(__name__)


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def round_size(sz: float, decimals: int) -> float:
    factor = 10 ** decimals
    return int(abs(sz) * factor) / factor * _sign(sz)  # trunca hacia 0 para no exceder límites


@dataclass
class Replicator:
    leaders: list[LeaderConfig]
    risk: RiskConfig
    sz_decimals: dict[str, int] = field(default_factory=dict)
    # (líder, moneda) -> signo de una posición que ya existía al arrancar y que NO copiamos
    ignored: dict[tuple[str, str], int] = field(default_factory=dict)
    # monedas en las que saltó nuestro stop: no se re-entra hasta que el líder cierre
    stopped: dict[str, int] = field(default_factory=dict)
    day_start_equity: float | None = None
    halted: bool = False
    _initialized: bool = False

    # ------------------------------------------------------------ objetivo
    def _weights(self) -> dict[str, float]:
        total = sum(l.weight for l in self.leaders) or 1.0
        return {l.address.lower(): l.weight / total for l in self.leaders}

    def _coin_allowed(self, coin: str) -> bool:
        if self.risk.allowed_coins and coin not in self.risk.allowed_coins:
            return False
        return coin not in self.risk.blocked_coins

    def initialize(self, leader_states: dict[str, AccountState]) -> None:
        """Registra las posiciones previas de los líderes para no entrar tarde en ellas."""
        if not self.risk.copy_existing_positions:
            for addr, st in leader_states.items():
                for coin, pos in st.positions.items():
                    self.ignored[(addr.lower(), coin)] = _sign(pos.size)
            if self.ignored:
                log.info("Ignorando %d posiciones preexistentes de los líderes", len(self.ignored))
        self._initialized = True

    def _refresh_ignored(self, leader_states: dict[str, AccountState]) -> None:
        for (addr, coin), sgn in list(self.ignored.items()):
            st = leader_states.get(addr)
            pos = st.positions.get(coin) if st else None
            if pos is None or _sign(pos.size) != sgn:  # el líder cerró o volteó: ya es una operación nueva
                del self.ignored[(addr, coin)]

    def target_positions(self, leader_states: dict[str, AccountState], my_equity: float,
                         mids: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
        """Devuelve (tamaño objetivo por moneda, precio de entrada medio ponderado del líder)."""
        weights = self._weights()
        targets: dict[str, float] = {}
        entry_num: dict[str, float] = {}
        for addr, st in leader_states.items():
            addr = addr.lower()
            w = weights.get(addr, 0.0)
            if w <= 0 or st.equity <= 0:
                continue
            ratio = my_equity * w / st.equity * self.risk.size_multiplier
            for coin, pos in st.positions.items():
                if (addr, coin) in self.ignored or not self._coin_allowed(coin):
                    continue
                sz = pos.size * ratio
                targets[coin] = targets.get(coin, 0.0) + sz
                entry_num[coin] = entry_num.get(coin, 0.0) + abs(sz) * pos.entry_px
        entries = {c: entry_num[c] / abs(targets[c]) for c in targets if targets[c] != 0}
        return self._apply_caps(targets, my_equity, mids), entries

    def _apply_caps(self, targets: dict[str, float], equity: float,
                    mids: dict[str, float]) -> dict[str, float]:
        max_coin = self.risk.max_position_pct * equity
        capped: dict[str, float] = {}
        for coin, sz in targets.items():
            px = mids.get(coin)
            if not px:
                continue
            notional = abs(sz) * px
            capped[coin] = sz * min(1.0, max_coin / notional) if notional > 0 else 0.0
        gross = sum(abs(sz) * mids[c] for c, sz in capped.items())
        max_gross = self.risk.max_leverage * equity
        if gross > max_gross > 0:
            scale = max_gross / gross
            capped = {c: sz * scale for c, sz in capped.items()}
        return capped

    # ------------------------------------------------------------- riesgo
    def _check_stops(self, me: AccountState, leader_targets: dict[str, float]) -> None:
        for coin, sgn in list(self.stopped.items()):
            if _sign(leader_targets.get(coin, 0.0)) != sgn:
                del self.stopped[coin]  # el líder ya salió/volteó: se puede volver a copiar
        for coin, pos in me.positions.items():
            if pos.notional > 0 and -pos.unrealized_pnl / pos.notional >= self.risk.stop_loss_pct:
                log.warning("Stop-loss en %s (PnL %.2f)", coin, pos.unrealized_pnl)
                self.stopped[coin] = _sign(pos.size)

    def _check_daily_limit(self, me: AccountState) -> None:
        if self.day_start_equity is None:
            self.day_start_equity = me.equity
        if me.equity < self.day_start_equity * (1 - self.risk.daily_loss_limit_pct):
            if not self.halted:
                log.error("Límite de pérdida diaria alcanzado: se cierra todo y se detiene la copia")
            self.halted = True

    def new_day(self, equity: float) -> None:
        self.day_start_equity = equity
        self.halted = False

    # -------------------------------------------------------------- órdenes
    def step(self, leader_states: dict[str, AccountState], me: AccountState,
             mids: dict[str, float]) -> list[Order]:
        if not self._initialized:
            self.initialize(leader_states)
        self._refresh_ignored(leader_states)
        self._check_daily_limit(me)

        if self.halted:
            targets, entries = {}, {}
        else:
            targets, entries = self.target_positions(leader_states, me.equity, mids)
            self._check_stops(me, targets)
            for coin, sgn in self.stopped.items():
                targets[coin] = 0.0 if _sign(targets.get(coin, 0.0)) == sgn else targets.get(coin, 0.0)

        orders: list[Order] = []
        for coin in sorted(set(targets) | set(me.positions)):
            current = me.positions[coin].size if coin in me.positions else 0.0
            target = targets.get(coin, 0.0)
            px = mids.get(coin)
            if not px:
                continue
            target = self._entry_guard(coin, current, target, px, entries.get(coin))
            orders.extend(self._diff_to_orders(coin, current, target, px))
        return orders

    def _entry_guard(self, coin: str, current: float, target: float, px: float,
                     leader_entry: float | None) -> float:
        """Evita perseguir el precio: no se abre ni aumenta si ya se movió demasiado a favor del líder."""
        increasing = _sign(target) != 0 and (_sign(current) != _sign(target) or abs(target) > abs(current))
        if not increasing or not leader_entry:
            return target
        dev = (px - leader_entry) / leader_entry * _sign(target)
        if dev > self.risk.max_entry_deviation_pct:
            log.info("%s: precio %.4f a %.2f%% de la entrada del líder %.4f, no se persigue",
                     coin, px, dev * 100, leader_entry)
            return current if _sign(current) == _sign(target) else 0.0
        return target

    def _diff_to_orders(self, coin: str, current: float, target: float, px: float) -> list[Order]:
        dec = self.sz_decimals.get(coin, 4)
        target = round_size(target, dec)
        delta = target - current
        if delta == 0:
            return []
        closing_fully = target == 0
        if not closing_fully and abs(delta) * px < self.risk.min_order_usd:
            return []
        if (not closing_fully and _sign(current) == _sign(target)
                and abs(delta) < self.risk.rebalance_threshold_pct * abs(target)):
            return []

        orders: list[Order] = []
        if current != 0 and (_sign(target) != _sign(current)):
            # cerrar primero (reduce-only) y luego abrir en sentido contrario si hace falta
            orders.append(Order(coin, is_buy=current < 0, sz=abs(current), reduce_only=True,
                                reason="cierre (el líder salió)" if target == 0 else "volteo"))
            if target != 0 and abs(target) * px >= self.risk.min_order_usd:
                orders.append(Order(coin, is_buy=target > 0, sz=abs(target), reason="entrada (volteo)"))
            return orders
        reducing = abs(target) < abs(current)
        orders.append(Order(coin, is_buy=delta > 0, sz=round(abs(delta), dec), reduce_only=reducing,
                            reason="reducción" if reducing else ("entrada" if current == 0 else "aumento")))
        return orders
