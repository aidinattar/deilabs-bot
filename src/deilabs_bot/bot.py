import os
import asyncio
from functools import partial

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from .config import DeilabsConfig
from .client import DeilabsClient
from .logger import Logger


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = user.id

    msg = (
        f"Hi {user.first_name}!\n\n"
        f"Your Telegram ID is: `{telegram_id}`.\n\n"
        "To enable lab presence logging, you (or the admin) must run this ON THE SERVER once:\n\n"
        f"`python cli.py login --user-id {telegram_id}`\n\n"
        "After that, you can use /punch to log your presence in the lab."
    )

    await update.message.reply_markdown(msg)


async def punch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    telegram_id = str(user.id)

    await update.message.reply_text("Checking / logging your lab presence, please wait...")

    # Run the blocking Playwright logic in a thread
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        partial(run_punch_for_user, telegram_id),
    )

    await update.message.reply_text(result)


def run_punch_for_user(telegram_id: str) -> str:
    """
    Synchronous helper that runs the DeilabsClient.ensure_presence()
    for a given Telegram user id. This will run in a thread, so it
    must be sync (no async/await here).
    """
    try:
        config = DeilabsConfig(
            user_id=telegram_id,
            lab_name="DEI/A | 230 DEI/A",  # TODO: later per-user configs
            debug=False,
        )
        client = DeilabsClient(config)
        msg = client.ensure_presence()
        Logger.log("bot_punch", msg, user_id=telegram_id, success=True)
        return msg
    except Exception as e:
        Logger.log("bot_punch_error", str(e), level="ERROR", user_id=telegram_id, success=False)
        return (
            "An error occurred while trying to log your presence.\n"
            "Possible reason: your session expired. "
            f"Try running again on the server:\n\n"
            f"`python cli.py login --user-id {telegram_id}`"
        )


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("punch", punch))

    print("Bot is running...")
    await application.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
