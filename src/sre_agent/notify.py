"""Notificação (Fase 2).

Interface `Notifier` + implementação Slack via incoming webhook. Telegram e
outros canais entram como novas implementações, sem tocar em quem notifica.

O agente só notifica quando há falha — nunca em estado saudável, para não virar
ruído.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from .config import NotifyConfig


@runtime_checkable
class Notifier(Protocol):
    def send(self, title: str, body: str) -> None: ...


class SlackNotifier:
    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    def send(self, title: str, body: str) -> None:
        payload = {
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": title}},
                {"type": "section", "text": {"type": "mrkdwn", "text": body}},
            ],
            # fallback de texto simples (notificações, clientes sem blocks)
            "text": f"{title}\n{body}",
        }
        resp = httpx.post(self._webhook_url, json=payload, timeout=10)
        resp.raise_for_status()


def build_notifier(config: NotifyConfig) -> Notifier | None:
    """Retorna um Notifier se a notificação estiver ativa e configurada."""
    if not config.enabled:
        return None
    if config.slack_webhook:
        return SlackNotifier(config.slack_webhook)
    return None
