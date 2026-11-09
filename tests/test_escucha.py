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


def test_locked_csv_keeps_rows_in_memory(monkeypatch, tmp_path):
    import copytrading.escucha as esc
    from copytrading.escucha import State, flush_rows
    target = tmp_path / "flujo.csv"
    monkeypatch.setattr(esc, "FLOW_CSV", target)
    st = State({})
    st.pending = [["2026-11-04 20:12", "BTC", 80000, 0, 0, 0, 0, 0, 0, 0, 0]]
    real_open = type(target).open

    def locked(self, *a, **k):
        raise PermissionError("abierto en Excel")
    monkeypatch.setattr(type(target), "open", locked)
    flush_rows(st)
    assert len(st.pending) == 1 and st.warned_locked                 # no se pierde ni se corta
    monkeypatch.setattr(type(target), "open", real_open)
    st.pending.append(["2026-11-04 20:13", "BTC", 80010, 0, 0, 0, 0, 0, 0, 0, 0])
    flush_rows(st)
    assert st.pending == [] and len(target.read_text().splitlines()) == 3   # cabecera + 2 filas


def test_hourly_activity_per_robot(monkeypatch, tmp_path):
    import copytrading.escucha as esc
    monkeypatch.setattr(esc, "HOURLY_CSV", tmp_path / "horario.csv")
    st = esc.State({"0xbot": "cazador", "0xmm": "creador de mercado"})
    st.add_trade({"coin": "BTC", "side": "B", "px": "80000", "sz": "1", "users": ["0xbot", "0xmm"]})
    esc.close_hour(st)
    rows = (tmp_path / "horario.csv").read_text().splitlines()
    assert len(rows) == 3 and any("0xbot,cazador,1,80000" in r for r in rows)


def test_heartbeat_line():
    from copytrading.escucha import State, heartbeat
    st = State({})
    st.price["BTC"] = 80000
    st.trades_seen = 1234
    for _ in range(15):
        st.net_hist["BTC"].append(-10_000)
    line = heartbeat(st, 15)
    assert line.startswith("✓ Funcionando: 1,234 operaciones en 15 min, sin avisos")
    assert "BTC 80,000 · cazadores venden neto $0.1M" in line


def test_hourly_push_and_liquidity_per_account(monkeypatch, tmp_path):
    import copytrading.escucha as esc
    monkeypatch.setattr(esc, "HOURLY_CSV", tmp_path / "h.csv")
    st = esc.State({"0xa": "sin confirmar", "0xb": "creador de mercado"})
    st.add_trade({"coin": "BTC", "side": "A", "px": "80000", "sz": "1", "users": ["0xb", "0xa"]})  # 0xa vende agresivo
    assert st.hourly["0xa"][3] == 80000 and st.hourly["0xb"][4] == 80000
    assert st.minute["BTC"] == {"otros|venta": 80000.0}          # 'sin confirmar' no entra en el flujo de robots


def test_failed_liquidity_fetch_is_not_zero():
    from copytrading.escucha import mm_liquidity

    class Src:
        def _info(self, payload):
            raise RuntimeError("HTTP 429")
    assert mm_liquidity(Src(), ["0xmm"], "BTC", 80000) is None


def test_winners_flow_drives_the_push_alert(monkeypatch, tmp_path):
    import copytrading.escucha as esc
    monkeypatch.setattr(esc, "EVENTS", tmp_path / "ev.jsonl")
    monkeypatch.setattr(esc, "FLOW_CSV", tmp_path / "f.csv")
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    st = esc.State({"0xwin": "sin confirmar", "0xbot": "cazador"})
    st.winners = {"0xwin"}
    st.price["BTC"] = 80000
    st.add_trade({"coin": "BTC", "side": "A", "px": "80000", "sz": "3", "users": ["0xmm", "0xwin"]})   # gana y vende
    st.add_trade({"coin": "BTC", "side": "B", "px": "80000", "sz": "1", "users": ["0xbot", "0xmm"]})   # cazador compra
    assert st.minute["BTC"]["ganadoras|venta"] == 240000.0
    for i in range(80):
        st.net_hist["BTC"].append(10_000 if i % 2 else -10_000)
    for _ in range(4):
        st.net_hist["BTC"].append(-200_000)
    esc.close_minute(st, None, [])                         # el minuto suma el flujo de las ganadoras, no el del cazador
    assert st.net_hist["BTC"][-1] == -240000.0
    ev = (tmp_path / "ev.jsonl").read_text()
    assert "las cuentas que ganan VENDEN" in ev and '"grupo": "ganadoras"' in ev
    row = (tmp_path / "f.csv").read_text().splitlines()[1].split(",")
    assert row[-2:] == ["0", "240000"]


def test_old_flow_csv_is_rotated(monkeypatch, tmp_path):
    import copytrading.escucha as esc
    old = tmp_path / "hft_flujo.csv"
    old.write_text("hora_col,moneda,precio\n2026-11-05 10:00,BTC,1\n", encoding="utf-8")
    moved = esc.rotate_old_flow(old)
    assert moved is not None and moved.exists() and not old.exists()
    assert esc.rotate_old_flow(old) is None


def _card_state():
    from types import SimpleNamespace
    import copytrading.escucha as esc
    st = esc.State({})
    st.price["BTC"] = 75222
    st.trend["BTC"] = "BAJISTA"
    for p in (75700, 75600, 75500, 75300, 75222):
        st.px_hist["BTC"].append(p)
    st.zones["BTC"] = ([SimpleNamespace(center=74681), SimpleNamespace(center=73204)],
                       [SimpleNamespace(center=77145)])
    return esc, st


SUNDAY = 1_794_174_721_737        # domingo 8 nov 16:52 (Colombia)


def test_trade_card_short_with_the_trend():
    esc, st = _card_state()
    text, card = esc.trade_card(st, "BTC", up=False, now_ms=SUNDAY)
    assert card and card["lado"] == "short" and card["tp1"] == round(73204 * 1.004, 2)   # 74.681 no paga 1,5R
    assert round(card["stop"]) == round(75700 * 1.0015) and card["r"] >= 1.5
    assert "FICHA CORTO BTC" in text


def test_trade_card_refuses_against_trend_and_on_saturday():
    esc, st = _card_state()
    text, card = esc.trade_card(st, "BTC", up=True, now_ms=SUNDAY)
    assert card is None and "Contra la tendencia" in text
    text, card = esc.trade_card(st, "BTC", up=False, now_ms=SUNDAY - 86_400_000)     # sábado
    assert card is None and "no se opera" in text


def test_winners_action_distinguishes_opening_from_closing():
    import copytrading.escucha as esc
    st = esc.State({})
    st.winners = {"0xw"}

    class Src:
        def _info(self, payload):
            return [{"coin": "BTC", "crossed": True, "side": "A", "dir": "Close Long", "px": "74780", "sz": "300"},
                    {"coin": "BTC", "crossed": True, "side": "A", "dir": "Open Short", "px": "74780", "sz": "10"},
                    {"coin": "ETH", "crossed": True, "side": "A", "dir": "Open Short", "px": "2100", "sz": "999"}]
    st.source = Src()
    got = esc.winners_action(st, "BTC", up=False)
    assert got["cierran"] == round(74780 * 300) and got["abren"] == round(74780 * 10)
    assert "cierran largos" in got["texto"] and "señal más débil" in got["texto"]
    st.source = None
    assert esc.winners_action(st, "BTC", up=False) is None
