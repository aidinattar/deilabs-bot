#!/usr/bin/env python3
import os
import json
import asyncio
from functools import partial
from typing import Dict, Any, Optional

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

from .config import DeilabsConfig
from .client import DeilabsClient
from .logger import Logger
from .labs   import LAB_CHOICES, LABS_PER_PAGE


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PREFS_FILE = "user_prefs.json"

# ---------------------------------------------------------------------
# Preferences helpers
# ---------------------------------------------------------------------
def load_prefs() -> Dict[str, Any]:
    if not os.path.exists(PREFS_FILE):
        return {}
    with open(PREFS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_prefs(prefs: Dict[str, Any]) -> None:
    with open(PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)


def get_lab_for_user(user_id: str) -> Optional[str]:
    prefs = load_prefs()
    user = prefs.get(str(user_id))
    if not user:
        return None
    return user.get("lab_name")


def set_lab_for_user(user_id: str, lab_name: str) -> None:
    prefs = load_prefs()
    prefs[str(user_id)] = {"lab_name": lab_name}
    save_prefs(prefs)


def resolve_lab(user_id: str, override: Optional[str] = None) -> str:
    if override:
        return override
    saved = get_lab_for_user(user_id)
    if saved:
        return saved
    return "DEI/A | 230 DEI/A"

def build_lab_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    """Build a paginated inline keyboard for selecting a lab."""
    total = len(LAB_CHOICES)
    max_page = (total - 1) // LABS_PER_PAGE

    page = max(0, min(page, max_page))

    start = page * LABS_PER_PAGE
    end = min(start + LABS_PER_PAGE, total)

    buttons = []

    for i in range(start, end):
        lab = LAB_CHOICES[i]
        buttons.append(
            [InlineKeyboardButton(lab, callback_data=f"setlab:{i}")]
        )

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅ Prev", callback_data=f"setlab_page:{page-1}"))
    if page < max_page:
        nav_row.append(InlineKeyboardButton("Next ➡", callback_data=f"setlab_page:{page+1}"))

    if nav_row:
        buttons.append(nav_row)

    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------
# Wrapper sync → async
# ---------------------------------------------------------------------
def run_ensure_presence(user_id: str, lab_name: str) -> str:
    cfg = DeilabsConfig(user_id=user_id, lab_name=lab_name, debug=False)
    client = DeilabsClient(cfg)
    return client.ensure_presence()


def run_status(user_id: str, lab_name: str) -> str:
    cfg = DeilabsConfig(user_id=user_id, lab_name=lab_name, debug=False)
    client = DeilabsClient(cfg)
    return client.get_status()


def run_exit(user_id: str, lab_name: str) -> str:
    cfg = DeilabsConfig(user_id=user_id, lab_name=lab_name, debug=False)
    client = DeilabsClient(cfg)
    return client.leave_lab()


# ---------------------------------------------------------------------
# Bot commands
# ---------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    lab = get_lab_for_user(uid)

    msg = (
        f"Hi {user.first_name}!\n\n"
        f"Your Telegram ID is: `{uid}`.\n\n"
        "Before using this bot, make sure you have already selected your *preferred laboratories* "
        "on the DeiLabs website (Labs in/out → Preferred labs page).\n\n"
        "Then, you must connect your UniPD session once from a machine with a GUI:\n\n"
        f"`deilabs login --user-id {uid}`\n\n"
        "After that, you can use the buttons or commands:\n"
        "• `/setlab` – set your default lab\n"
        "• `/status` – check your current status\n"
        "• `/punch` – enter the lab if needed\n"
        "• `/exit` – leave the lab\n"
    )

    if lab:
        msg += f"\nCurrent default lab: `{lab}`"

    keyboard = ReplyKeyboardMarkup(
        [["/status", "/punch"], ["/exit", "/setlab"]],
        resize_keyboard=True,
    )

    await update.message.reply_markdown(msg, reply_markup=keyboard)


async def login_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    msg = (
        "To connect your UniPD DeiLabs session to this bot, run this command "
        "from a graphical session (or via `ssh -X`) on the server where the bot runs:\n\n"
        f"`deilabs login --user-id {uid}`\n\n"
        "Once done, you can use /punch, /status and /exit normally."
    )
    await update.message.reply_markdown(msg)


async def setlab_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)

    # manual lab name provided
    if context.args:
        lab_name = " ".join(context.args).strip()
        set_lab_for_user(uid, lab_name)
        await update.message.reply_text(
            f"Default lab for your account has been set to:\n{lab_name}"
        )
        return

    # show lab selection keyboard
    markup = build_lab_keyboard(page=0)

    await update.message.reply_text(
        "Select your default lab from the list below:",
        reply_markup=markup,
    )


async def setlab_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    uid = str(user.id)

    data = query.data
    _, idx_str = data.split(":", 1)
    idx = int(idx_str)

    if 0 <= idx < len(LAB_CHOICES):
        lab_name = LAB_CHOICES[idx]
        set_lab_for_user(uid, lab_name)
        await query.edit_message_text(
            f"Default lab for your account has been set to:\n{lab_name}"
        )
    else:
        await query.edit_message_text(
            "Invalid lab selection. Please try /setlab again."
        )


async def setlab_page_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    _, page_str = data.split(":", 1)
    page = int(page_str)

    markup = build_lab_keyboard(page=page)

    await query.edit_message_reply_markup(reply_markup=markup)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    lab = resolve_lab(uid)

    await update.message.reply_text("Checking your current lab status...")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        partial(run_status, uid, lab),
    )

    await update.message.reply_text(result)


async def punch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    lab = resolve_lab(uid)

    await update.message.reply_text(f"Ensuring presence in lab:\n{lab}\nPlease wait...")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        partial(run_ensure_presence, uid, lab),
    )

    await update.message.reply_text(result)


async def exit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    lab = resolve_lab(uid)

    await update.message.reply_text("Trying to leave the lab...")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        partial(run_exit, uid, lab),
    )

    await update.message.reply_text(result)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("login", login_info))
    application.add_handler(CommandHandler("setlab", setlab_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("punch", punch_cmd))
    application.add_handler(CommandHandler("exit", exit_cmd))

    application.add_handler(CallbackQueryHandler(setlab_button, pattern=r"^setlab:\d+$"))
    application.add_handler(CallbackQueryHandler(setlab_page_button, pattern=r"^setlab_page:\d+$"))

    Logger.log("bot_start", "Telegram bot started.", user_id=None)
    application.run_polling()


if __name__ == "__main__":
    main()