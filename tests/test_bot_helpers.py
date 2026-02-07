import json
from pathlib import Path

from deilabs_bot import bot


def test_validate_session_file_ok(tmp_path):
    path = tmp_path / "session.json"
    payload = {
        "cookies": [{"domain": ".dei.unipd.it", "name": "sid", "value": "x"}],
        "origins": [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    ok, msg = bot._validate_session_file(path)
    assert ok is True
    assert msg == ""


def test_validate_session_file_rejects_bad_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not-json", encoding="utf-8")

    ok, msg = bot._validate_session_file(path)
    assert ok is False
    assert "not valid JSON" in msg


def test_validate_session_file_rejects_missing_cookies(tmp_path):
    path = tmp_path / "nocookies.json"
    path.write_text(json.dumps({"cookies": []}), encoding="utf-8")

    ok, msg = bot._validate_session_file(path)
    assert ok is False
    assert "No cookies were found" in msg


def test_infer_success_cases():
    assert bot._infer_success("Presence logged successfully for lab: X") is True
    assert bot._infer_success("Could not click Enter button.") is False
    assert bot._infer_success("Random neutral message") is None


def test_derive_current_state_cases():
    state_in = bot._derive_current_state("LAB-X", "punch", "You are already inside the lab.")
    assert state_in is not None
    assert state_in[0] == "inside"
    assert state_in[1] == "LAB-X"
    assert isinstance(state_in[2], str)

    state_out = bot._derive_current_state("LAB-X", "exit", "You have exited the lab.")
    assert state_out == ("outside", None, None)

    state_unknown = bot._derive_current_state("LAB-X", "status", "Session expired: please run again.")
    assert state_unknown == ("unknown", None, None)


def test_get_known_users_merges_sources(monkeypatch):
    monkeypatch.setattr(bot, "list_current_status_users", lambda: [("1", "u1"), ("2", None)])
    monkeypatch.setattr(bot, "load_prefs", lambda: {"2": {"lab_name": "L2"}, "3": {"lab_name": "L3"}})

    users = bot.get_known_users()
    assert users == {"1": "u1", "2": None, "3": None}


def test_safe_filename_strips_unsafe_chars():
    name = bot._safe_filename("auth 1743$%^.json")
    assert name == "auth_1743_.json"


def test_validate_session_file_with_non_dict(tmp_path):
    path = Path(tmp_path) / "array.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    ok, msg = bot._validate_session_file(path)
    assert ok is False
    assert "must contain a JSON object" in msg
