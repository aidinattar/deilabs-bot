import os
import re
import uuid 
import json
import shutil
import asyncio
from datetime import datetime, timezone
from functools import partial
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

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
    MessageHandler,
    filters,
)

from .config import DeilabsConfig
from .client import DeilabsClient
from .logger import Logger
from .labs   import LAB_CHOICES, LABS_PER_PAGE
from .auth_server import LOGIN_TOKENS

UPLOADS_DIR = Path("uploads")
AUTH_DIR = Path("auth")
SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")

# TODO: change this to web server URL in production
WEB_AUTH_URL = os.getenv("WEB_AUTH_URL", "http://localhost:5000")
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


def _timestamp() -> str:
    """UTC timestamp for audit file naming."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _validate_session_file(path: Path) -> Tuple[bool, str]:
    """Lightweight validation to avoid storing malformed Playwright sessions."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError:
        return False, "The uploaded file is not valid JSON. Run `deilabs login` again and resend it."
    except OSError:
        return False, "Could not read the uploaded file. Please try again."

    if not isinstance(data, dict):
        return False, "The session file must contain a JSON object."

    cookies = data.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        return (
            False,
            "No cookies were found. Run `deilabs login` again and resend the new file.",
        )

    has_dei_cookie = any(
        isinstance(cookie, dict)
        and "domain" in cookie
        and "dei.unipd.it" in str(cookie.get("domain", "")).lower()
        for cookie in cookies
    )

    if not has_dei_cookie:
        return (
            False,
            "The file does not look like a DeiLabs session (cookies missing). Upload the correct file.",
        )

    return True, ""


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
        "Once the session file `auth_{uid}.json` is created, just send it here as a *document* "
        "to upload it (or use /login if you have the hosted web flow).\n\n"
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


async def login_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a token, associate it with the user, and send an external link for interactive login."""
    user = update.effective_user
    uid = str(user.id)
    
    if not WEB_AUTH_URL or "localhost" in WEB_AUTH_URL:
        await update.message.reply_text(
            "Configuration Error: The web login URL is not set correctly. "
            "Please set the WEB_AUTH_URL environment variable to your public address."
        )
        return

    token = str(uuid.uuid4())
    
    # Note: the token will be removed after the first use (or timeout) by the web server.
    LOGIN_TOKENS[token] = uid 
    
    auth_url = f"{WEB_AUTH_URL}/auth?token={token}"

    Logger.log("login_link_generated", f"Generated auth link for user {uid}", url=auth_url)

    keyboard = [
        [InlineKeyboardButton("🔗 Go to UniPD Login Page", url=auth_url)],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Click the button to start the interactive login flow.\n"
        "You will be redirected to the **official login page** of the University of Padova. "
        "After completing the login, your session will be securely saved.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )


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


# ---------------------------------------------------------------------
# Session upload helpers
# ---------------------------------------------------------------------
def _safe_filename(name: str) -> str:
    name = (name or "").strip().replace(" ", "_")
    name = SAFE_NAME_RE.sub("_", name)
    return name[:180] if len(name) > 180 else name

async def upload_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return

    doc = update.message.document
    if doc is None:
        await update.message.reply_text("Send the file as a document.")
        return

    # Optional: limit size (e.g. 10MB)
    if doc.file_size and doc.file_size > 10 * 1024 * 1024:
        await update.message.reply_text("File too large (max 10MB).")
        return

    uid = str(user.id)
    user_dir = UPLOADS_DIR / uid
    user_dir.mkdir(parents=True, exist_ok=True)

    AUTH_DIR.mkdir(parents=True, exist_ok=True)

    original = _safe_filename(doc.file_name or f"file_{doc.file_unique_id}.json")
    audit_name = f"{_timestamp()}__{doc.file_unique_id}__{original}"
    audit_path = user_dir / audit_name

    tg_file = await context.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(custom_path=str(audit_path))

    is_valid, err = _validate_session_file(audit_path)
    if not is_valid:
        try:
            if audit_path.exists():
                audit_path.unlink()
        except OSError:
            pass
        await update.message.reply_text(err)
        return

    final_name = f"auth_{uid}.json"
    final_path = AUTH_DIR / final_name
    backup_path = final_path.with_suffix(".bak")
    if final_path.exists():
        shutil.copyfile(final_path, backup_path)
    shutil.copyfile(audit_path, final_path)

    await update.message.reply_text(
        "Session updated successfully. You can now run /punch, /status, or /exit.")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    # application.add_handler(CommandHandler("login", login_info))
    application.add_handler(CommandHandler("login", login_cmd))
    application.add_handler(CommandHandler("setlab", setlab_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("punch", punch_cmd))
    application.add_handler(CommandHandler("exit", exit_cmd))
    application.add_handler(MessageHandler(filters.Document.ALL, upload_document))

    application.add_handler(CallbackQueryHandler(setlab_button, pattern=r"^setlab:\d+$"))
    application.add_handler(CallbackQueryHandler(setlab_page_button, pattern=r"^setlab_page:\d+$"))

    Logger.log("bot_start", "Telegram bot started.", user_id=None)
    application.run_polling()


if __name__ == "__main__":
    main()
