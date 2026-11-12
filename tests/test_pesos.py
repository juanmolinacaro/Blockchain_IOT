from copytrading.pesos import MIN_N, weight


def test_weight_scale():
    assert weight(0.5, 100) == 0 and weight(0.45, 100) == 0
    assert weight(0.75, 100) == 1.0 and weight(1.0, 100) == 2.0
    assert weight(0.9, MIN_N - 1) == 1.0                    # pocos casos: neutro


def test_weighted_confirmation_and_coordination():
    from collections import deque
    import copytrading.escucha as esc
    st = esc.State({})
    st.trend["BTC"] = "BAJISTA"
    for _ in range(30):
        st.crowd_hist["BTC"].append(100_000)
    st.whale_pos["BTC"] = deque([(0, -5e6), (1, -6e6)])
    st.pesos = {"tendencia": 1.0, "público": 0.2, "ballenas": 0.0}
    c = esc.confirmation(st, "BTC")
    assert c["puntaje"] == -1.2 and "puntaje -1.2" in c["texto"]
    ok, verdict = esc.coordinates(c, short=True)
    assert not ok and "puntaje ≥ 2" in verdict
