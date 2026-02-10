"""Shared helpers for user lab preferences."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from .paths import PREFS_FILE as DEFAULT_PREFS_FILE

PREFS_FILE = str(DEFAULT_PREFS_FILE)
DEFAULT_LAB = "DEI/A | 230 DEI/A"


def _initialize_empty_prefs_file() -> None:
    """Best-effort write of an empty prefs object."""
    try:
        save_prefs({})
    except OSError:
        return


def load_prefs() -> Dict[str, Any]:
    """Load user preferences from disk."""
    if not os.path.exists(PREFS_FILE):
        return {}

    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as handle:
            content = handle.read()
    except OSError:
        return {}

    if not content.strip():
        _initialize_empty_prefs_file()
        return {}

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}

    return data


def save_prefs(prefs: Dict[str, Any]) -> None:
    """Persist user preferences to disk."""
    parent = os.path.dirname(PREFS_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(PREFS_FILE, "w", encoding="utf-8") as handle:
        json.dump(prefs, handle, indent=2)


def get_lab_for_user(user_id: str) -> Optional[str]:
    """Return saved lab for a user, if available."""
    prefs = load_prefs()
    user = prefs.get(str(user_id))
    if not user:
        return None
    return user.get("lab_name")


def set_lab_for_user(user_id: str, lab_name: str) -> None:
    """Store default lab for a user."""
    prefs = load_prefs()
    prefs[str(user_id)] = {"lab_name": lab_name}
    save_prefs(prefs)


def resolve_lab(user_id: str, override: Optional[str] = None) -> str:
    """Resolve effective lab using explicit value, saved value, then default."""
    if override:
        return override
    saved = get_lab_for_user(user_id)
    if saved:
        return saved
    return DEFAULT_LAB
