from copytrading.binance_escucha import BinanceState, build_row, parse_force_order


def test_force_order_long_liquidation():
    msg = {"stream": "btcusdt@forceOrder", "data": {"e": "forceOrder", "o": {
        "s": "BTCUSDT", "S": "SELL", "q": "2", "p": "75000", "ap": "75100", "z": "2"}}}
    assert parse_force_order(msg) == ("BTC", "largos", 150200.0)
    msg["data"]["o"]["S"] = "BUY"
    assert parse_force_order(msg)[1] == "cortos"
    assert parse_force_order({"data": {"o": {"s": "DOGEUSDT"}}}) is None


def test_build_row_and_summary():
    kline = [0, "80000", "80100", "79900", "80050", "10", 0, "800000", 100, "6", "500000", "0"]
    st = BinanceState()
    st.add_liq("BTC", "largos", 1_200_000)
    row = build_row("BTC", "2026-11-05 10:00", kline, {"openInterest": "90000"}, {"lastFundingRate": "0.0001"},
                    st.liq["BTC"], {"top": 1.4, "cuentas": 2.1})
    assert row == ["2026-11-05 10:00", "BTC", 80050.0, 800000, 500000, 300000, 90000.0, 0.0001, 1200000, 0, 1.4, 2.1]
    st.recent["BTC"] = [row]
    assert "liquidado largos $1.2M" in st.summary()


def test_force_order_array_format():
    msg = {"stream": "!forceOrder@arr", "data": {"e": "forceOrder", "o": {
        "s": "ETHUSDT", "S": "BUY", "q": "10", "p": "2300", "ap": "2301", "z": "10"}}}
    assert parse_force_order(msg) == ("ETH", "cortos", 23010.0)
