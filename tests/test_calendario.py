from datetime import date

from copytrading import calendario as cal


def test_ny_to_colombia_with_us_daylight_saving():
    assert cal.ny_to_cot(date(2026, 12, 10), "08:30").strftime("%H:%M") == "08:30"     # invierno: igual
    assert cal.ny_to_cot(date(2026, 7, 10), "08:30").strftime("%H:%M") == "07:30"      # verano: una hora menos


def test_events_for_day_includes_weekly():
    c = {"eventos": [{"fecha": "2026-12-10", "hora_ny": "08:30", "nombre": "IPC", "impacto": "alto"}],
         "recurrentes": [{"dia_semana": 3, "hora_ny": "08:30", "nombre": "Desempleo", "impacto": "medio"}]}
    ev = cal.events_for(c, date(2026, 12, 10))                                          # jueves
    assert [e["nombre"] for e in ev] == ["IPC", "Desempleo"]
    assert "⚠ ALTO" in cal.describe(ev)
    assert cal.events_for(c, date(2026, 12, 11)) == []
