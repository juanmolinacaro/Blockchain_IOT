"""Bucle en vivo: sondea a los líderes, calcula órdenes y las ejecuta."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from .config import Config
from .models import AccountState
from .replicator import Replicator
from .sources.base import DataSource

log = logging.getLogger(__name__)


def run(cfg: Config, source: DataSource, executor, max_iterations: int | None = None) -> Replicator:
    if not cfg.leaders:
        raise ValueError("No hay líderes configurados. Usa `discover` y añádelos al config.")
    replicator = Replicator(cfg.leaders, cfg.risk, sz_decimals=source.size_decimals())
    current_day = datetime.now(timezone.utc).date()
    i = 0
    while max_iterations is None or i < max_iterations:
        i += 1
        try:
            mids = source.mid_prices()
            leaders: dict[str, AccountState] = {
                l.address.lower(): source.account_state(l.address) for l in cfg.leaders
            }
            me = executor.state(mids)
            today = datetime.now(timezone.utc).date()
            if today != current_day:
                current_day = today
                replicator.new_day(me.equity)
            for order in replicator.step(leaders, me, mids):
                executor.execute(order, mids[order.coin], int(time.time() * 1000))
            log.debug("equity=%.2f posiciones=%s", me.equity,
                      {c: p.size for c, p in me.positions.items()})
        except Exception:  # un fallo de red no debe tumbar el bot
            log.exception("Error en la iteración %d", i)
        if max_iterations is None or i < max_iterations:
            time.sleep(cfg.poll_seconds)
    return replicator
