"""Local development: long polling instead of a webhook (leave PUBLIC_BASE_URL empty).

    python -m app.run_polling
"""
import logging

from app.bot import ALLOWED_UPDATES, build_application, log_privacy_mode
from app.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)


async def post_init(app) -> None:
    await init_db()
    await log_privacy_mode(app)


def main() -> None:
    app = build_application(with_updater=True)
    app.post_init = post_init
    app.run_polling(allowed_updates=ALLOWED_UPDATES)   # also removes any webhook


if __name__ == "__main__":
    main()
