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


def test_regime_weights_fall_back_to_all(tmp_path):
    from copytrading.pesos import for_regime, load, regime, save
    assert regime(-0.03) == "bajista" and regime(0.025) == "alcista" and regime(0.01) == "rango"
    p = tmp_path / "p.json"
    save({"todos": {"mayoría": {"peso": 0.75, "acierto": 0.69, "n": 600}, "público": {"peso": 0.2, "acierto": 0.55, "n": 500}},
          "bajista": {"mayoría": {"peso": 1.37, "acierto": 0.84, "n": 89}, "público": {"peso": 1.0, "acierto": 0.9, "n": 5}}}, p)
    w = load(p)
    assert for_regime(w, "bajista") == {"mayoría": 1.37, "público": 0.2}     # público: pocos casos en bajista
    assert for_regime(w, "alcista") == {"mayoría": 0.75, "público": 0.2}
