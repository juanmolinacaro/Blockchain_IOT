from copytrading.sources.hyperliquid import (
    HyperliquidSource,
    parse_clearinghouse_state,
    parse_fill,
    parse_leaderboard_row,
)


def test_parse_fill():
    raw = {"coin": "ETH", "px": "3000.5", "sz": "0.2", "side": "A", "time": 1700000000000,
           "startPosition": "0.5", "dir": "Close Long", "closedPnl": "12.3", "fee": "0.27"}
    f = parse_fill(raw)
    assert f.signed_sz == -0.2
    assert abs(f.end_position - 0.3) < 1e-12
    assert f.is_closing and f.closed_pnl == 12.3


def test_parse_clearinghouse_state_skips_flat_positions():
    raw = {
        "marginSummary": {"accountValue": "50000.0"},
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "-0.5", "entryPx": "60000", "unrealizedPnl": "100",
                          "leverage": {"type": "cross", "value": 5}}},
            {"position": {"coin": "SOL", "szi": "0.0", "entryPx": None, "unrealizedPnl": "0"}},
        ],
    }
    st = parse_clearinghouse_state("0xabc", raw)
    assert st.equity == 50000.0
    assert list(st.positions) == ["BTC"]
    assert st.positions["BTC"].size == -0.5 and st.positions["BTC"].leverage == 5


def test_parse_leaderboard_row():
    row = {"ethAddress": "0xabc", "accountValue": "123456.7",
           "windowPerformances": [["day", {"pnl": "10", "roi": "0.01", "vlm": "1000"}],
                                  ["month", {"pnl": "5000", "roi": "0.2", "vlm": "90000"}]]}
    e = parse_leaderboard_row(row)
    assert e.address == "0xabc" and e.pnl["month"] == 5000 and e.roi["day"] == 0.01


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def request(self, method, url, **kw):
        self.calls.append(kw.get("json"))
        return FakeResp(self.pages.pop(0))


def test_fills_paginates(monkeypatch):
    monkeypatch.setattr("copytrading.sources.hyperliquid.MAX_FILLS_PER_PAGE", 2)
    mk = lambda t: {"coin": "BTC", "px": "1", "sz": "1", "side": "B", "time": t, "startPosition": "0"}
    session = FakeSession([[mk(1), mk(2)], [mk(3)]])
    fills = HyperliquidSource(session=session).fills("0xabc", 0)
    assert [f.time for f in fills] == [1, 2, 3]
    assert session.calls[1]["startTime"] == 3
