from copytrading.chart import Level, Summary, _k, plan_name, plan_positions, render
from copytrading.cli import _plain_event
from copytrading.method.monitor import manual_plan
from copytrading.models import Candle
from copytrading.notify import send_ntfy_image


def _candles(n=60, px=77000.0):
    out = []
    for i in range(n):
        o = px + (i % 7 - 3) * 80
        out.append(Candle(i * 4 * 3_600_000, o, o + 150, o - 150, o + (60 if i % 2 else -60), 1000.0))
    return out


def test_short_price_format():
    assert _k(76766.4) == "76.766"
    assert _k(93.54) == "93,5"


def test_plan_positions_like_tradingview_tool():
    e = manual_plan("BTC", "short", 77250, "below", 78100, 76470, 74800, interval="4h",
                    note="D: rompe la bandera", now_ms=1_793_648_010_684)
    assert plan_name(e.note) == "Plan D"
    [pos] = plan_positions([e], "BTC")
    assert (pos.name, pos.side, pos.pending, pos.entry) == ("D", "short", True, 77250)
    assert pos.cond == "si cierra 4H < 77.250"
    assert round(pos.rr, 2) == round((77250 - 74800) / (78100 - 77250), 2)
    assert plan_positions([e], "ETH") == []


def test_render_writes_png(tmp_path):
    path = tmp_path / "btc.png"
    s = Summary("BTC", 77000, "VIGILAR", ["Rompió hacia abajo (77.231): parece TRAMPA"], ["Plan D: venta"])
    e = manual_plan("BTC", "short", 77250, "below", 78100, 76470, 74800, note="D: x", now_ms=10 * 3_600_000)
    render(str(path), _candles(), s, [Level(76000, "liquidez largos 76.000", "#7e57c2", band=200)],
           positions=plan_positions([e], "BTC"))
    assert path.read_bytes()[:4] == b"\x89PNG"


def test_plain_event():
    assert _plain_event("🎯 BTC plan short ACTIVADO en 77,077.0 (D: rompe)") == "Plan D ACTIVADO: venta en 77.077"
    assert _plain_event("✅ BTC juan cerrada +0.10R (breakeven)") == "Operación cerrada: +0.10R (breakeven)"


def test_send_ntfy_image_puts_file_with_utf8_params(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG....")
    calls = {}

    class Resp:
        def raise_for_status(self):
            pass

    class Session:
        def put(self, url, data, timeout, params, headers):
            calls.update(url=url, data=data, params=params, headers=headers)
            return Resp()

    assert send_ntfy_image("👀 BTC · VIGILAR", "Rompió hacia abajo", "VIGILAR", "t", str(img),
                           server="https://x", session=Session())
    assert calls["url"] == "https://x/t" and calls["data"].startswith(b"\x89PNG")
    assert calls["params"]["title"] == "👀 BTC · VIGILAR" and calls["headers"]["Filename"] == "a.png"


def test_send_image_alert_uses_telegram_photo(tmp_path, monkeypatch):
    from copytrading.notify import send_image_alert
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG....")
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    calls = {}

    class Resp:
        def raise_for_status(self):
            pass

    class Session:
        def post(self, url, timeout, data, files):
            calls.update(url=url, data=data, name=files["photo"][0])
            return Resp()

    assert send_image_alert("👀 BTC · VIGILAR", "texto", str(img), session=Session()) == ["telegram"]
    assert calls["url"].endswith("/bottok/sendPhoto") and calls["data"]["chat_id"] == "42"
    assert calls["data"]["caption"].startswith("👀 BTC · VIGILAR\n\ntexto")
