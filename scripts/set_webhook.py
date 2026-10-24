"""(Re)register the Telegram webhook for the hosted bot, e.g. after testing locally with polling.

    python scripts/set_webhook.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telegram import Bot  # noqa: E402

from app.bot import ALLOWED_UPDATES  # noqa: E402
from app.config import settings  # noqa: E402


async def main():
    if not settings.PUBLIC_BASE_URL:
        sys.exit("Set PUBLIC_BASE_URL in .env first.")
    url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/webhook"
    async with Bot(settings.TELEGRAM_BOT_TOKEN) as bot:
        await bot.set_webhook(url=url, secret_token=settings.APP_SECRET, allowed_updates=ALLOWED_UPDATES)
        print("Webhook set:", (await bot.get_webhook_info()).url)


if __name__ == "__main__":
    asyncio.run(main())
