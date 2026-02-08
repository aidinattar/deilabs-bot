import os
import re
import json
import shutil
import asyncio
from datetime import datetime, timezone, time
from functools import partial
from typing import Dict, Optional, Tuple
from pathlib import Path
from zoneinfo import ZoneInfo

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
from .prefs import load_prefs, get_lab_for_user, set_lab_for_user, resolve_lab
from .db import (
    init_db,
    log_session_upload,
    log_status_event,
    update_current_status,
    list_current_status_users,
    list_current_status_snapshot,
    reset_all_statuses,
)

UPLOADS_DIR = Path("uploads")
AUTH_DIR = Path("auth")
SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_TIMEZONE = ZoneInfo(os.getenv("BOT_TIMEZONE", "Europe/Rome"))
ADMIN_USER_IDS = {
    uid.strip() for uid in os.getenv("ADMIN_USER_IDS", "").split(",") if uid.strip()
}
STATUS_FILTERS = {"all", "inside", "outside", "unknown"}
try:
    STATUS_PAGE_SIZE = max(1, int(os.getenv("ADMIN_STATUS_PAGE_SIZE", "10")))
except ValueError:
    STATUS_PAGE_SIZE = 10

init_db()


def get_known_users() -> Dict[str, Optional[str]]:
    """Return mapping of user_id -> last known username."""
    known: Dict[str, Optional[str]] = {}
    for uid, username in list_current_status_users():
        known[uid] = username

    prefs = load_prefs()
    for uid in prefs.keys():
        known.setdefault(uid, None)

    return known


def _is_admin(user_id: str) -> bool:
    return user_id in ADMIN_USER_IDS


def _build_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Send 10:00 Reminder", callback_data="admin:ping")],
            [InlineKeyboardButton("Run 13:00 Status Check", callback_data="admin:check")],
            [InlineKeyboardButton("Reset All to Outside", callback_data="admin:reset")],
            [InlineKeyboardButton("View Current Status", callback_data="admin:status")],
        ]
    )


def _format_status_table(
    rows: list[tuple[str, Optional[str], str, Optional[str], Optional[str], str]],
    start_index: int = 1,
) -> str:
    if not rows:
        return "No users found in current_status."

    lines = []
    for idx, (uid, username, status, lab_name, entered_at, updated_at) in enumerate(rows, start=start_index):
        lines.append(
            "\n".join(
                [
                    f"{idx}. uid={uid}",
                    f"   user={username or '-'}",
                    f"   state={status or '-'}",
                    f"   lab={lab_name or '-'}",
                    f"   entered={entered_at or '-'}",
                    f"   updated={updated_at or '-'}",
                ]
            )
        )

    return "\n\n".join(lines)


def _slice_status_rows(
    rows: list[tuple[str, Optional[str], str, Optional[str], Optional[str], str]],
    state_filter: str,
    page: int,
) -> tuple[list[tuple[str, Optional[str], str, Optional[str], Optional[str], str]], int, int, int, str]:
    normalized_filter = state_filter if state_filter in STATUS_FILTERS else "all"
    if normalized_filter == "all":
        filtered = rows[:]
    else:
        filtered = [row for row in rows if row[2] == normalized_filter]

    filtered.sort(key=lambda row: (row[5] or "", row[0]), reverse=True)
    total = len(filtered)
    max_page = max(0, (total - 1) // STATUS_PAGE_SIZE)
    page = max(0, min(page, max_page))
    start = page * STATUS_PAGE_SIZE
    end = start + STATUS_PAGE_SIZE
    return filtered[start:end], page, max_page, total, normalized_filter


def _build_status_keyboard(state_filter: str, page: int, max_page: int) -> InlineKeyboardMarkup:
    current_filter = state_filter if state_filter in STATUS_FILTERS else "all"
    buttons = [
        [
            InlineKeyboardButton(
                f"{name.upper()}{'*' if name == current_filter else ''}",
                callback_data=f"adminstatus:{name}:0",
            )
            for name in ("all", "inside", "outside", "unknown")
        ]
    ]
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("Prev", callback_data=f"adminstatus:{current_filter}:{page-1}"))
    if page < max_page:
        nav_row.append(InlineKeyboardButton("Next", callback_data=f"adminstatus:{current_filter}:{page+1}"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton("Back", callback_data="admin:menu")])
    return InlineKeyboardMarkup(buttons)


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


def _infer_success(status_text: str) -> Optional[bool]:
    """Best-effort inference of successful Telegram commands."""
    lowered = status_text.lower()
    failure_markers = ["session expired", "could not", "error", "uncertain"]
    if any(marker in lowered for marker in failure_markers):
        return False

    success_markers = [
        "presence logged successfully",
        "you are already inside",
        "you are not in any lab",
        "you have exited the lab",
    ]
    if any(marker in lowered for marker in success_markers):
        return True

    return None


def _derive_current_state(
    lab_name: str,
    command: str,
    status_text: str,
) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    """Map textual responses to a structured user state."""
    lowered = status_text.lower()
    now_iso = datetime.now(timezone.utc).isoformat()

    if "presence logged successfully" in lowered or "you are already inside" in lowered:
        return ("inside", lab_name, now_iso)

    if "you are not in any lab" in lowered or "you have exited the lab" in lowered:
        return ("outside", None, None)

    if "session expired" in lowered or "laboratories are currently closed" in lowered:
        return ("unknown", None, None)

    if any(marker in lowered for marker in ["could not", "error", "invalid"]):
        return ("unknown", None, None)

    return None


async def _auto_status_update(uid: str, username: Optional[str]) -> None:
    lab = resolve_lab(uid)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            partial(run_status, uid, lab),
        )
    except Exception as exc:
        result = f"Automatic status check failed: {exc}"

    log_status_event(
        user_id=uid,
        username=username,
        lab_name=lab,
        command="auto_status",
        status_text=result,
        success=_infer_success(result),
    )
    derived = _derive_current_state(lab, "auto_status", result)
    if derived:
        status_name, derived_lab, entered_at = derived
        update_current_status(
            user_id=uid,
            username=username,
            status=status_name,
            lab_name=(derived_lab or ""),
            last_entered_at=entered_at,
        )


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
        "to upload it.\n\n"
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
        "from a graphical session (or via `ssh -X`) on the machine where the bot runs:\n\n"
        f"`deilabs login --user-id {uid}`\n\n"
        "After login, grab the generated `auth_{uid}.json` file and send it here as a *document*.\n"
        "Once uploaded, you can use /punch, /status, and /exit normally."
    )
    await update.message.reply_markdown(msg)


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    uid = str(user.id)
    if not _is_admin(uid):
        await update.message.reply_text("Not authorized.")
        return

    await update.message.reply_text(
        "Admin actions:",
        reply_markup=_build_admin_keyboard(),
    )


async def _render_admin_status(query, state_filter: str, page: int):
    rows = list_current_status_snapshot()
    page_rows, page, max_page, total, normalized_filter = _slice_status_rows(rows, state_filter, page)
    keyboard = _build_status_keyboard(normalized_filter, page, max_page)
    start_index = page * STATUS_PAGE_SIZE + 1
    table = _format_status_table(page_rows, start_index=start_index)
    await query.edit_message_text(
        f"Current status snapshot\n"
        f"filter={normalized_filter} page={page + 1}/{max_page + 1} total={total} page_size={STATUS_PAGE_SIZE}\n\n"
        f"{table}",
        reply_markup=keyboard,
    )


async def admin_action_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query or not query.from_user:
        return

    uid = str(query.from_user.id)
    if not _is_admin(uid):
        await query.answer("Not authorized.", show_alert=True)
        return

    data = query.data
    if data == "admin:menu":
        await query.edit_message_text("Admin actions:", reply_markup=_build_admin_keyboard())
        return

    if data.startswith("adminstatus:"):
        _, state_filter, page_str = data.split(":", 2)
        try:
            page = int(page_str)
        except ValueError:
            page = 0
        await _render_admin_status(query, state_filter, page)
        return

    action = data.split(":", 1)[1]
    if action == "ping":
        await query.edit_message_text("Sending reminder to known users...")
        result = await morning_ping_job(context)
        await query.edit_message_text(
            f"Reminder sent. total={result['total']} sent={result['sent']} "
            f"failed={result['failed']} skipped={result['skipped']}"
        )
        return

    if action == "check":
        await query.edit_message_text("Running status check for known users...")
        result = await midday_status_job(context)
        await query.edit_message_text(
            f"Status check completed. total={result['total']} checked={result['checked']}"
        )
        return

    if action == "reset":
        await query.edit_message_text("Resetting all current statuses to outside...")
        result = await midnight_reset_job(context)
        await query.edit_message_text(
            f"Reset completed. rows_updated={result['updated']}"
        )
        return

    if action == "status":
        await _render_admin_status(query, "all", 0)
        return

    await query.edit_message_text("Unknown admin action.")


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

    log_status_event(
        user_id=uid,
        username=user.username,
        lab_name=lab,
        command="status",
        status_text=result,
        success=_infer_success(result),
    )
    derived = _derive_current_state(lab, "status", result)
    if derived:
        status_name, derived_lab, entered_at = derived
        update_current_status(
            user_id=uid,
            username=user.username,
            status=status_name,
            lab_name=(derived_lab or ""),
            last_entered_at=entered_at,
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

    log_status_event(
        user_id=uid,
        username=user.username,
        lab_name=lab,
        command="punch",
        status_text=result,
        success=_infer_success(result),
    )
    derived = _derive_current_state(lab, "punch", result)
    if derived:
        status_name, derived_lab, entered_at = derived
        update_current_status(
            user_id=uid,
            username=user.username,
            status=status_name,
            lab_name=(derived_lab or ""),
            last_entered_at=entered_at,
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

    log_status_event(
        user_id=uid,
        username=user.username,
        lab_name=lab,
        command="exit",
        status_text=result,
        success=_infer_success(result),
    )
    derived = _derive_current_state(lab, "exit", result)
    if derived:
        status_name, derived_lab, entered_at = derived
        update_current_status(
            user_id=uid,
            username=user.username,
            status=status_name,
            lab_name=(derived_lab or ""),
            last_entered_at=entered_at,
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
    log_session_upload(
        user_id=uid,
        username=user.username,
        source_path=str(audit_path),
        stored_path=str(final_path),
    )

    await update.message.reply_text(
        "Session updated successfully. You can now run /punch, /status, or /exit.")


async def midnight_reset_job(context: ContextTypes.DEFAULT_TYPE):
    updated = reset_all_statuses()
    Logger.log(
        "scheduler_midnight_reset",
        f"All statuses reset to outside. rows_updated={updated}",
        user_id=None,
    )
    return {"updated": updated}


async def morning_ping_job(context: ContextTypes.DEFAULT_TYPE):
    users = get_known_users()
    if not users:
        return {"total": 0, "sent": 0, "failed": 0, "skipped": 0}

    keyboard = ReplyKeyboardMarkup(
        [["/punch", "/status"], ["/login", "/setlab"]],
        resize_keyboard=True,
    )
    text = (
        "Good morning! Are you already in the lab?\n\n"
        "Remember to run /punch when you enter. Need to refresh your session or choose another lab? "
        "Use the buttons below."
    )

    sent = 0
    failed = 0
    skipped = 0
    for uid in users.keys():
        try:
            chat_id = int(uid)
        except ValueError:
            skipped += 1
            continue
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
            sent += 1
        except Exception as exc:
            failed += 1
            Logger.log(
                "scheduler_morning_ping_error",
                f"Could not send reminder to {uid}: {exc}",
                level="ERROR",
                user_id=uid,
            )
    return {"total": len(users), "sent": sent, "failed": failed, "skipped": skipped}


async def midday_status_job(context: ContextTypes.DEFAULT_TYPE):
    users = get_known_users()
    if not users:
        return {"total": 0, "checked": 0}

    checked = 0
    for uid, username in users.items():
        await _auto_status_update(uid, username)
        checked += 1
    return {"total": len(users), "checked": checked}


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    Logger.log(
        "bot_unhandled_exception",
        f"Unhandled exception: {context.error}",
        level="ERROR",
        user_id=None,
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("login", login_info))
    application.add_handler(CommandHandler("admin", admin_cmd))
    application.add_handler(CommandHandler("setlab", setlab_cmd))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("punch", punch_cmd))
    application.add_handler(CommandHandler("exit", exit_cmd))
    application.add_handler(MessageHandler(filters.Document.ALL, upload_document))

    application.add_handler(
        CallbackQueryHandler(
            admin_action_button,
            pattern=r"^(admin:(ping|check|reset|status|menu)|adminstatus:(all|inside|outside|unknown):\d+)$",
        )
    )
    application.add_handler(CallbackQueryHandler(setlab_button, pattern=r"^setlab:\d+$"))
    application.add_handler(CallbackQueryHandler(setlab_page_button, pattern=r"^setlab_page:\d+$"))
    application.add_error_handler(_on_error)

    Logger.log("bot_start", "Telegram bot started.", user_id=None)
    job_queue = application.job_queue
    if job_queue is None:
        Logger.log(
            "job_queue_missing",
            "Job queue not available. Install python-telegram-bot[job-queue] to enable scheduled tasks.",
            level="WARNING",
            user_id=None,
        )
    else:
        job_queue.run_daily(midnight_reset_job, time=time(hour=0, minute=0, tzinfo=BOT_TIMEZONE))
        job_queue.run_daily(morning_ping_job, time=time(hour=10, minute=0, tzinfo=BOT_TIMEZONE))
        job_queue.run_daily(midday_status_job, time=time(hour=13, minute=0, tzinfo=BOT_TIMEZONE))
    application.run_polling()


if __name__ == "__main__":
    main()
