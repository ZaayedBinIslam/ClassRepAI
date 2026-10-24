"""Builds the python-telegram-bot Application and registers handlers."""
import logging

from telegram import Update
from telegram.ext import (Application, ChatMemberHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from app.config import settings
from app.handlers.lifecycle import on_my_chat_member, on_start
from app.handlers.messages import on_message

log = logging.getLogger(__name__)

ALLOWED_UPDATES = ["message", "my_chat_member"]


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(update.effective_chat.id, "Something went wrong, please try again.")
        except Exception:
            pass


def build_application(with_updater: bool) -> Application:
    builder = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).concurrent_updates(True)
    if not with_updater:
        builder = builder.updater(None)
    app = builder.build()
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("start", on_start, filters=filters.ChatType.PRIVATE))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & filters.UpdateType.MESSAGE, on_message))
    app.add_error_handler(on_error)
    return app


async def log_privacy_mode(app: Application) -> None:
    me = await app.bot.get_me()
    if not me.can_read_all_group_messages:
        log.warning("Privacy mode is ON: the bot only sees mentions in groups. "
                    "Disable it in @BotFather (/setprivacy -> Disable) for chat context.")
    log.info("Running as @%s", me.username)
