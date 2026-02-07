import sqlite3

from deilabs_bot import db


def _tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row[0] for row in rows}


def test_init_db_creates_expected_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "deilabs.sqlite3")
    monkeypatch.setattr(db, "_INITIALIZED", False)

    db.init_db(force=True)

    with sqlite3.connect(db.DB_PATH) as conn:
        tables = _tables(conn)

    assert "session_uploads" in tables
    assert "status_events" in tables
    assert "current_status" in tables


def test_log_session_upload_persists_row(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "deilabs.sqlite3")
    monkeypatch.setattr(db, "_INITIALIZED", False)
    db.init_db(force=True)

    db.log_session_upload("123", "aidin", "/tmp/a.json", "auth/auth_123.json")

    with sqlite3.connect(db.DB_PATH) as conn:
        row = conn.execute(
            "SELECT user_id, username, source_path, stored_path FROM session_uploads"
        ).fetchone()

    assert row == ("123", "aidin", "/tmp/a.json", "auth/auth_123.json")


def test_update_current_status_upsert_and_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "deilabs.sqlite3")
    monkeypatch.setattr(db, "_INITIALIZED", False)
    db.init_db(force=True)

    db.update_current_status(
        user_id="1",
        username="alice",
        status="inside",
        lab_name="LAB-A",
        last_entered_at="2026-02-07T09:00:00+00:00",
    )
    db.update_current_status(
        user_id="1",
        username="alice_2",
        status="outside",
        lab_name="",
        last_entered_at=None,
    )

    with sqlite3.connect(db.DB_PATH) as conn:
        row = conn.execute(
            "SELECT user_id, username, status, lab_name, last_entered_at FROM current_status"
        ).fetchone()
    assert row == ("1", "alice_2", "outside", "", None)

    db.reset_all_statuses()
    with sqlite3.connect(db.DB_PATH) as conn:
        row_after = conn.execute(
            "SELECT status, lab_name, last_entered_at FROM current_status WHERE user_id = '1'"
        ).fetchone()
    assert row_after == ("outside", None, None)


def test_list_current_status_users(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "deilabs.sqlite3")
    monkeypatch.setattr(db, "_INITIALIZED", False)
    db.init_db(force=True)

    db.update_current_status("10", "user10", "outside", None, None)
    db.update_current_status("20", None, "unknown", None, None)

    users = set(db.list_current_status_users())
    assert ("10", "user10") in users
    assert ("20", None) in users
