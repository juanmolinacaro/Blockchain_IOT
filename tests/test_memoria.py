from copytrading.method.memoria import matching_cases, record_case


def test_cases_match_by_shared_patterns(tmp_path):
    path = tmp_path / "casos.json"
    assert record_case("BTC", "2026-11-05", "trampa alcista", ["tendencia_bajista", "trampa_alcista"],
                       "cayó 6 %", path)
    assert not record_case("BTC", "2026-11-05", "otra vez", ["x"], "y", path)       # mismo día: no se repite
    import json
    cases = json.loads(path.read_text())
    later = "2026-12-01"
    assert matching_cases("BTC", ["tendencia_bajista", "trampa_alcista", "iman_abajo"], cases, today=later)
    assert not matching_cases("BTC", ["tendencia_bajista"], cases, today=later)                   # comparte solo 1
    assert not matching_cases("ETH", ["tendencia_bajista", "trampa_alcista"], cases, today=later)  # otra moneda
    assert not matching_cases("BTC", ["tendencia_bajista", "trampa_alcista"], cases, today="2026-11-06")  # mismo episodio
    assert not record_case("BTC", "2026-11-06", "auto", ["x"], "y", path)                         # 1 día después: ya anotado
