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
from sqlalchemy.exc import SQLAlchemyError

from core.alerting import DiscordEmitter, TelegramEmitter, build_digest
from core.db import get_session, init_db
from core.db.repository import JobRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and send a job digest.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", help="print, don't send")
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be greater than zero")

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    discord = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not args.dry_run and bool(tg_token) != bool(tg_chat):
        print(
            "Telegram delivery requires both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. "
            "Set both, remove both, or use --dry-run.",
            file=sys.stderr,
        )
        return 1

    try:
        init_db()
        with get_session() as session:
            rows = JobRepository(session).list(include_duplicates=False)
            digest = build_digest(rows, limit=args.limit)
    except (SQLAlchemyError, ValueError, ImportError) as exc:
        print(
            "Cannot read the job database. Check DATABASE_URL, database permissions, "
            f"and migrations ({type(exc).__name__}).",
            file=sys.stderr,
        )
        return 1

    markdown = digest.to_markdown()
    print(markdown)

    if args.dry_run:
        return 0

    channels: list[tuple[str, TelegramEmitter | DiscordEmitter]] = []
    if tg_token and tg_chat:
        channels.append(("Telegram", TelegramEmitter(tg_token, tg_chat)))
    if discord:
        channels.append(("Discord", DiscordEmitter(discord)))
    if not channels:
        print("No delivery channel configured; nothing sent.", file=sys.stderr)
        return 0

    failed = False
    with httpx.Client() as client:
        for name, emitter in channels:
            try:
                delivered = emitter.send(digest, client)
            except (httpx.HTTPError, httpx.InvalidURL):
                delivered = False
            if delivered:
                print(f"{name} digest delivered.")
            else:
                # Exceptions may include the Telegram token/webhook URL. Never
                # print them or retry a possibly completed delivery blindly.
                print(
                    f"{name} delivery failed; check channel settings and connectivity.",
                    file=sys.stderr,
                )
                failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
