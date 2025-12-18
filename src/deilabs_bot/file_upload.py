from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


@dataclass(frozen=True)
class UploadConfig:
    uploads_dir: Path = Path("uploads")
    allowed_user_ids: Optional[set[int]] = None  # None = allow all
    max_bytes: int = 20 * 1024 * 1024  # 20MB (Telegram bot download limit can apply)


def _safe_filename(name: str) -> str:
    name = name.strip().replace(" ", "_")
    name = SAFE_NAME_RE.sub("_", name)
    return name[:180] if len(name) > 180 else name


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


async def handle_document_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    cfg: UploadConfig,
) -> None:
    if not update.effective_user or not update.message:
        return

    uid = update.effective_user.id
    if cfg.allowed_user_ids is not None and uid not in cfg.allowed_user_ids:
        await update.message.reply_text("Not allowed.")
        return

    doc = update.message.document
    if doc is None:
        await update.message.reply_text("Please send a file as a document.")
        return

    if doc.file_size and doc.file_size > cfg.max_bytes:
        await update.message.reply_text("File too large.")
        return

    if doc.mime_type not in {"application/json", "text/plain"}:
        await update.message.reply_text("Unsupported file type.")
        return

    user_dir = cfg.uploads_dir / str(uid)
    user_dir.mkdir(parents=True, exist_ok=True)

    original = doc.file_name or f"file_{doc.file_unique_id}"
    original = _safe_filename(original)

    dst_name = f"{_timestamp()}__{doc.file_unique_id}__{original}"
    dst_path = user_dir / dst_name

    tg_file = await context.bot.get_file(doc.file_id)
    # download_to_drive is the supported method for PTB v20+ :contentReference[oaicite:0]{index=0}
    await tg_file.download_to_drive(custom_path=str(dst_path))

    await update.message.reply_text(f"Saved as:\n{dst_path}")
