"""Centralized filesystem paths for persistent bot data."""

from __future__ import annotations

import os
from pathlib import Path


def _path_from_env(var_name: str, default: Path) -> Path:
    value = os.getenv(var_name)
    if value:
        return Path(value).expanduser()
    return default.expanduser()


DATA_DIR = _path_from_env("DEILABS_DATA_DIR", Path("."))
AUTH_DIR = _path_from_env("DEILABS_AUTH_DIR", DATA_DIR / "auth")
UPLOADS_DIR = _path_from_env("DEILABS_UPLOADS_DIR", DATA_DIR / "uploads")
LOGS_DIR = _path_from_env("DEILABS_LOGS_DIR", DATA_DIR / "logs")
PREFS_FILE = _path_from_env("DEILABS_PREFS_FILE", DATA_DIR / "user_prefs.json")
DB_PATH = _path_from_env("DEILABS_DB_PATH", LOGS_DIR / "deilabs.sqlite3")
