import sqlite3
from contextlib import closing
from typing import Optional, List, Tuple

from .paths import DB_PATH as DEFAULT_DB_PATH

DB_PATH = DEFAULT_DB_PATH
_INITIALIZED = False


def _ensure_parent() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_parent()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(force: bool = False) -> None:
    global _INITIALIZED
    if _INITIALIZED and not force:
        return

    with closing(_connect()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS session_uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                username TEXT,
                source_path TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS status_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                username TEXT,
                lab_name TEXT,
                command TEXT NOT NULL,
                status_text TEXT NOT NULL,
                success INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS current_status (
                user_id TEXT PRIMARY KEY,
                username TEXT,
                status TEXT NOT NULL,
                lab_name TEXT,
                last_entered_at TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.commit()
    _INITIALIZED = True


def log_session_upload(
    user_id: str,
    username: Optional[str],
    source_path: str,
    stored_path: str,
) -> None:
    init_db()
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO session_uploads (user_id, username, source_path, stored_path)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, username, source_path, stored_path),
        )
        conn.commit()


def log_status_event(
    user_id: str,
    username: Optional[str],
    lab_name: str,
    command: str,
    status_text: str,
    success: Optional[bool] = None,
) -> None:
    init_db()
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO status_events (user_id, username, lab_name, command, status_text, success)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, username, lab_name, command, status_text, None if success is None else int(success)),
        )
        conn.commit()


def update_current_status(
    user_id: str,
    username: Optional[str],
    status: str,
    lab_name: Optional[str],
    last_entered_at: Optional[str],
) -> None:
    init_db()
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO current_status (user_id, username, status, lab_name, last_entered_at, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                status=excluded.status,
                lab_name=excluded.lab_name,
                last_entered_at=excluded.last_entered_at,
                updated_at=datetime('now')
            """,
            (user_id, username, status, lab_name, last_entered_at),
        )
        conn.commit()


def list_current_status_users() -> List[Tuple[str, Optional[str]]]:
    init_db()
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT user_id, username FROM current_status"
        ).fetchall()
    return [(row["user_id"], row["username"]) for row in rows]


def list_current_status_snapshot() -> List[Tuple[str, Optional[str], str, Optional[str], Optional[str], str]]:
    init_db()
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT user_id, username, status, lab_name, last_entered_at, updated_at
            FROM current_status
            ORDER BY user_id ASC
            """
        ).fetchall()
    return [
        (
            row["user_id"],
            row["username"],
            row["status"],
            row["lab_name"],
            row["last_entered_at"],
            row["updated_at"],
        )
        for row in rows
    ]


def reset_all_statuses(status: str = "outside") -> int:
    init_db()
    with closing(_connect()) as conn:
        cursor = conn.execute(
            """
            UPDATE current_status
            SET status = ?, lab_name = NULL, last_entered_at = NULL, updated_at = datetime('now')
            """,
            (status,),
        )
        conn.commit()
    return cursor.rowcount


if __name__ == "__main__":
    init_db(force=True)
    print(f"Database ready at {DB_PATH}")
