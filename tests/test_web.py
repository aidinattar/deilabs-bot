import pytest

pytest.importorskip("flask")

import deilabs_bot.web as web


def test_index_groups_online_and_offline(monkeypatch):
    monkeypatch.setattr(
        web,
        "list_current_status_snapshot",
        lambda: [
            ("1", "alice", "inside", "LAB-A", "2026-02-14T09:00:00+00:00", "2026-02-14 09:00:01"),
            ("2", "bob", "outside", "", None, "2026-02-14 09:00:02"),
            ("3", None, "unknown", "", None, "2026-02-14 09:00:03"),
        ],
    )
    app = web.create_app()
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Online" in html
    assert "Offline" in html
    assert "alice" in html
    assert "bob" in html
    assert "user_3" in html


def test_api_status_payload(monkeypatch):
    monkeypatch.setattr(
        web,
        "list_current_status_snapshot",
        lambda: [
            ("10", "u10", "inside", "LAB-I", "2026-02-14T10:00:00+00:00", "2026-02-14 10:00:01"),
            ("20", "u20", "outside", "", None, "2026-02-14 10:00:02"),
        ],
    )
    app = web.create_app()
    client = app.test_client()

    response = client.get("/api/status")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 2
    assert payload["online_count"] == 1
    assert payload["offline_count"] == 1
    assert payload["online"][0]["user_id"] == "10"
