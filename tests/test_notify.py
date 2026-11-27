import base64

import pytest
import requests

from copytrading import notify


class FakeResp:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, status=200):
        self.calls, self.status = [], status

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return FakeResp(self.status)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("NTFY_TOPIC", "NTFY_SERVER", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)


def test_ntfy_message_format():
    s = FakeSession()
    assert notify.send_alert("🚨 SEÑAL: BTC long", "detalle", "SEÑAL", ntfy_topic="tema-x", session=s) == ["ntfy"]
    url, kw = s.calls[0]
    assert url == "https://ntfy.sh/tema-x"
    assert kw["data"] == "detalle".encode()
    assert kw["headers"]["Priority"] == "urgent"
    title = kw["headers"]["Title"]
    assert base64.b64decode(title[10:-2]).decode() == "🚨 SEÑAL: BTC long"
    assert all(ord(ch) < 128 for v in kw["headers"].values() for ch in v)   # cabeceras ASCII


def test_telegram_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    s = FakeSession()
    assert notify.send_alert("t", "b", session=s) == ["telegram"]
    url, kw = s.calls[0]
    assert url.endswith("/bot123:abc/sendMessage") and kw["json"]["chat_id"] == "42"


def test_failures_are_reported_not_raised():
    assert notify.send_alert("t", "b", ntfy_topic="x", session=FakeSession(status=500)) == []
    assert notify.send_alert("t", "b", session=FakeSession()) == []    # sin canal configurado
