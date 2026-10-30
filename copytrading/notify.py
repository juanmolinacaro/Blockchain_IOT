"""Envío de alertas al móvil, sin depender de la plataforma donde corre el monitor.

Canales:
  * ntfy (https://ntfy.sh): app gratuita de notificaciones push. Basta con suscribirse en la
    app a un tema (topic) con un nombre difícil de adivinar. Variable: NTFY_TOPIC
    (o --ntfy-topic). Servidor propio opcional: NTFY_SERVER.
  * Telegram: bot propio creado con @BotFather. Variables: TELEGRAM_BOT_TOKEN y
    TELEGRAM_CHAT_ID. El token es secreto: va en las variables del entorno, nunca en el repo.
"""
from __future__ import annotations

import base64
import logging
import os

import requests

log = logging.getLogger(__name__)

PRIORITY = {"SEÑAL": "urgent", "CERRADA": "high", "VIGILAR": "default", "PRUEBA": "default"}
TAGS = {"SEÑAL": "rotating_light", "CERRADA": "white_check_mark", "VIGILAR": "eyes", "PRUEBA": "test_tube"}


def send_ntfy(title: str, body: str, level: str, topic: str, server: str | None = None,
              session: requests.Session | None = None) -> bool:
    server = (server or os.environ.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
    http = session or requests
    resp = http.post(f"{server}/{topic}", data=body.encode("utf-8"), timeout=15, headers={
        # las cabeceras HTTP deben ser ASCII: ntfy acepta títulos UTF-8 codificados según RFC 2047
        "Title": "=?UTF-8?B?" + base64.b64encode(title.encode()).decode() + "?=",
        "Priority": PRIORITY.get(level, "default"),
        "Tags": TAGS.get(level, "chart_with_upwards_trend"),
    })
    resp.raise_for_status()
    return True


def send_telegram(title: str, body: str, token: str, chat_id: str,
                  session: requests.Session | None = None) -> bool:
    http = session or requests
    resp = http.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=15,
                     json={"chat_id": chat_id, "text": f"{title}\n\n{body}"})
    resp.raise_for_status()
    return True


def send_alert(title: str, body: str, level: str = "VIGILAR", ntfy_topic: str | None = None,
               session: requests.Session | None = None) -> list[str]:
    """Envía por todos los canales configurados. Devuelve los canales que funcionaron."""
    sent = []
    topic = ntfy_topic or os.environ.get("NTFY_TOPIC")
    if topic:
        try:
            send_ntfy(title, body, level, topic, session=session)
            sent.append("ntfy")
        except requests.RequestException as exc:
            log.error("ntfy falló: %s", exc)
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            send_telegram(title, body, token, chat, session=session)
            sent.append("telegram")
        except requests.RequestException as exc:
            log.error("Telegram falló: %s", exc)
    if not topic and not (token and chat):
        log.warning("Sin canal de alertas configurado (NTFY_TOPIC o TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)")
    return sent
