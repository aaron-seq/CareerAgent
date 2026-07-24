"""Alerting: build job digests and deliver them (RSS/Telegram/Discord)."""

from .digest import Digest, DigestItem, build_digest
from .emitters import DiscordEmitter, TelegramEmitter

__all__ = [
    "Digest",
    "DigestItem",
    "build_digest",
    "DiscordEmitter",
    "TelegramEmitter",
]
