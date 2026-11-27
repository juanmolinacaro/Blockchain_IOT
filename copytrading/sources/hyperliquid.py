"""Cliente de solo lectura para la API pública de Hyperliquid.

No requiere claves: todas las posiciones y fills de cualquier wallet son
públicos en el L1 de Hyperliquid.
Docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
"""
from __future__ import annotations

import time

import requests

from ..models import AccountState, Candle, Fill, LeaderboardEntry, Position

API_URLS = {
    "mainnet": "https://api.hyperliquid.xyz",
    "testnet": "https://api.hyperliquid-testnet.xyz",
}
LEADERBOARD_URLS = {
    "mainnet": "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard",
    "testnet": "https://stats-data.hyperliquid-testnet.xyz/Testnet/leaderboard",
}
MAX_FILLS_PER_PAGE = 2000


class HyperliquidSource:
    def __init__(self, network: str = "mainnet", session: requests.Session | None = None,
                 timeout: float = 15.0, max_retries: int = 4):
        self.base_url = API_URLS[network]
        self.leaderboard_url = LEADERBOARD_URLS[network]
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self._sz_decimals: dict[str, int] | None = None

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, url: str, **kwargs):
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                return resp.json()
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
                if attempt == self.max_retries:
                    raise
                time.sleep(2 ** attempt)

    def _info(self, payload: dict):
        return self._request("POST", f"{self.base_url}/info", json=payload)

    # --------------------------------------------------------------- lecturas
    def leaderboard(self) -> list[LeaderboardEntry]:
        data = self._request("GET", self.leaderboard_url)
        return [parse_leaderboard_row(row) for row in data.get("leaderboardRows", [])]

    def fills(self, address: str, start_ms: int, end_ms: int | None = None) -> list[Fill]:
        """Fills en [start_ms, end_ms], paginando hacia delante en el tiempo."""
        out: list[Fill] = []
        cursor = start_ms
        while True:
            payload = {"type": "userFillsByTime", "user": address, "startTime": cursor,
                       "aggregateByTime": True}
            if end_ms is not None:
                payload["endTime"] = end_ms
            page = self._info(payload) or []
            out.extend(parse_fill(f) for f in page)
            if len(page) < MAX_FILLS_PER_PAGE:
                break
            cursor = max(int(f["time"]) for f in page) + 1
        out.sort(key=lambda f: f.time)
        return out

    def account_state(self, address: str) -> AccountState:
        return parse_clearinghouse_state(address, self._info({"type": "clearinghouseState", "user": address}))

    def mid_prices(self) -> dict[str, float]:
        return {coin: float(px) for coin, px in self._info({"type": "allMids"}).items()}

    def candles(self, coin: str, interval: str, start_ms: int, end_ms: int) -> list[Candle]:
        """Velas OHLCV. Hyperliquid solo conserva las ~5000 más recientes por intervalo."""
        out: dict[int, Candle] = {}
        cursor = start_ms
        while cursor < end_ms:
            page = self._info({"type": "candleSnapshot",
                               "req": {"coin": coin, "interval": interval,
                                       "startTime": cursor, "endTime": end_ms}}) or []
            for raw in page:
                c = parse_candle(raw)
                out[c.t] = c
            if len(page) < 5000:
                break
            cursor = int(page[-1]["t"]) + 1
        return [out[t] for t in sorted(out)]

    def size_decimals(self) -> dict[str, int]:
        if self._sz_decimals is None:
            meta = self._info({"type": "meta"})
            self._sz_decimals = {a["name"]: int(a["szDecimals"]) for a in meta["universe"]}
        return self._sz_decimals


# ------------------------------------------------------------------ parsers
def parse_fill(raw: dict) -> Fill:
    return Fill(
        coin=raw["coin"],
        px=float(raw["px"]),
        sz=float(raw["sz"]),
        side=raw["side"],
        time=int(raw["time"]),
        start_position=float(raw.get("startPosition", 0.0)),
        closed_pnl=float(raw.get("closedPnl", 0.0)),
        fee=float(raw.get("fee", 0.0)),
        direction=raw.get("dir", ""),
    )


def parse_candle(raw: dict) -> Candle:
    return Candle(t=int(raw["t"]), o=float(raw["o"]), h=float(raw["h"]), l=float(raw["l"]),
                  c=float(raw["c"]), v=float(raw["v"]))


def parse_clearinghouse_state(address: str, raw: dict) -> AccountState:
    positions: dict[str, Position] = {}
    for item in raw.get("assetPositions", []):
        p = item["position"]
        size = float(p["szi"])
        if size == 0:
            continue
        lev = p.get("leverage") or {}
        positions[p["coin"]] = Position(
            coin=p["coin"],
            size=size,
            entry_px=float(p.get("entryPx") or 0.0),
            unrealized_pnl=float(p.get("unrealizedPnl") or 0.0),
            leverage=float(lev.get("value", 1.0)) if isinstance(lev, dict) else float(lev),
            liquidation_px=float(p["liquidationPx"]) if p.get("liquidationPx") else None,
        )
    equity = float(raw.get("marginSummary", {}).get("accountValue", 0.0))
    return AccountState(address=address, equity=equity, positions=positions)


def parse_leaderboard_row(row: dict) -> LeaderboardEntry:
    pnl, roi, vlm = {}, {}, {}
    for window, perf in row.get("windowPerformances", []):
        pnl[window] = float(perf.get("pnl", 0.0))
        roi[window] = float(perf.get("roi", 0.0))
        vlm[window] = float(perf.get("vlm", 0.0))
    return LeaderboardEntry(
        address=row["ethAddress"],
        account_value=float(row.get("accountValue", 0.0)),
        pnl=pnl, roi=roi, volume=vlm,
    )
