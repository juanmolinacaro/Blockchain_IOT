"""Ejecutor real en Hyperliquid usando el SDK oficial (`pip install hyperliquid-python-sdk`).

Seguridad:
  * Usa una *API wallet* (agent wallet) creada en app.hyperliquid.xyz/API: puede
    operar pero NO puede retirar fondos.
  * La clave privada se lee de la variable de entorno HL_SECRET_KEY, nunca del repo.
  * Pruébalo primero en testnet (network = "testnet").
"""
from __future__ import annotations

import logging
import os

from ..models import AccountState, Order
from ..sources.hyperliquid import API_URLS, HyperliquidSource

log = logging.getLogger(__name__)


class HyperliquidLiveExecutor:
    def __init__(self, network: str, account_address: str | None = None, slippage: float = 0.01):
        try:
            import eth_account
            from hyperliquid.exchange import Exchange
        except ImportError as exc:  # pragma: no cover - depende de un paquete opcional
            raise RuntimeError("Instala el SDK: pip install hyperliquid-python-sdk") from exc

        secret = os.environ.get("HL_SECRET_KEY")
        if not secret:
            raise RuntimeError("Define HL_SECRET_KEY con la clave de tu API wallet")
        wallet = eth_account.Account.from_key(secret)
        self.account_address = account_address or os.environ.get("HL_ACCOUNT_ADDRESS") or wallet.address
        self.exchange = Exchange(wallet, API_URLS[network], account_address=self.account_address)
        self.source = HyperliquidSource(network)
        self.slippage = slippage

    def state(self, mids: dict[str, float]) -> AccountState:
        return self.source.account_state(self.account_address)

    def execute(self, order: Order, mid: float, time_ms: int = 0) -> float | None:
        if order.reduce_only:
            result = self.exchange.market_close(order.coin, sz=order.sz, slippage=self.slippage)
        else:
            result = self.exchange.market_open(order.coin, order.is_buy, order.sz, slippage=self.slippage)
        log.info("[LIVE] %s %s %s -> %s", "BUY" if order.is_buy else "SELL", order.coin, order.sz, result)
        if not result or result.get("status") != "ok":
            log.error("Orden rechazada: %s", result)
            return None
        for status in result["response"]["data"]["statuses"]:
            if "filled" in status:
                return float(status["filled"]["avgPx"])
            if "error" in status:
                log.error("Error en orden %s: %s", order.coin, status["error"])
        return None
