from copytrading.escucha import State, check_signals


def test_trades_are_split_by_aggressor_type():
    st = State({"0xbot": "cazador"})
    st.add_trade({"coin": "BTC", "side": "A", "px": "80000", "sz": "2", "users": ["0xmm", "0xbot"]})  # robot vende
    st.add_trade({"coin": "BTC", "side": "B", "px": "80000", "sz": "1", "users": ["0xx", "0xy"]})
    assert st.minute["BTC"] == {"cazador|venta": 160000.0, "otros|compra": 80000.0}


def test_hunter_push_alert(monkeypatch, tmp_path):
    import copytrading.escucha as esc
    monkeypatch.setattr(esc, "EVENTS", tmp_path / "ev.jsonl")
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    st = State({})
    st.price["BTC"] = 80000
    for i in range(80):
        st.net_hist["BTC"].append(10_000 if i % 2 else -10_000)
    for _ in range(5):
        st.net_hist["BTC"].append(-200_000)          # 5 min de ventas agresivas de cazadores
    check_signals(st, "BTC")
    assert "VENDEN" in (tmp_path / "ev.jsonl").read_text()
