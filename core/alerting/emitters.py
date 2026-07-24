"""
Digest delivery channels.

Telegram and Discord webhooks over an injected ``httpx.Client`` so delivery is
mockable in tests (no live network in CI). RSS output is just a string the
caller can write to a file or serve.
"""

from __future__ import annotations

import httpx

from .digest import Digest


class TelegramEmitter:
    """Send a digest to a Telegram chat via the Bot API."""

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, digest: Digest, client: httpx.Client) -> bool:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        resp = client.post(
            url,
            json={
                "chat_id": self.chat_id,
                "text": digest.to_markdown(),
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=15.0,
        )
        return resp.status_code == 200


class DiscordEmitter:
    """Post a digest to a Discord channel via an incoming webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, digest: Digest, client: httpx.Client) -> bool:
        resp = client.post(
            self.webhook_url,
            json={"content": digest.to_markdown()[:2000]},
            timeout=15.0,
        )
        return resp.status_code in (200, 204)
