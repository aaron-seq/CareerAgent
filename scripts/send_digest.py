"""
Build (and optionally send) a job digest from the database.

Run locally or from the scheduled GitHub Action (see
.github/workflows/digest.yml). With ``--dry-run`` it prints the Markdown digest
and sends nothing -- safe for CI. To deliver, set the relevant env vars:

    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   -> Telegram
    DISCORD_WEBHOOK_URL                    -> Discord

Usage:
    python -m scripts.send_digest --dry-run
    python -m scripts.send_digest --limit 15
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

from core.alerting import DiscordEmitter, TelegramEmitter, build_digest
from core.db import get_session, init_db
from core.db.repository import JobRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and send a job digest.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", help="print, don't send")
    args = parser.parse_args(argv)

    init_db()
    with get_session() as session:
        rows = JobRepository(session).list(include_duplicates=False)
        digest = build_digest(rows, limit=args.limit)

    markdown = digest.to_markdown()
    print(markdown)

    if args.dry_run:
        return 0

    sent_any = False
    with httpx.Client() as client:
        tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
        if tg_token and tg_chat:
            TelegramEmitter(tg_token, tg_chat).send(digest, client)
            sent_any = True
        discord = os.environ.get("DISCORD_WEBHOOK_URL")
        if discord:
            DiscordEmitter(discord).send(digest, client)
            sent_any = True

    if not sent_any:
        print("No delivery channel configured; nothing sent.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
