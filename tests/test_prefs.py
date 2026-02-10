import json

import deilabs_bot.prefs as prefs


def test_load_prefs_missing_file_returns_empty(monkeypatch, tmp_path):
    prefs_file = tmp_path / "user_prefs.json"
    monkeypatch.setattr(prefs, "PREFS_FILE", str(prefs_file))

    assert prefs.load_prefs() == {}


def test_load_prefs_empty_file_returns_empty_and_initializes(monkeypatch, tmp_path):
    prefs_file = tmp_path / "user_prefs.json"
    prefs_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(prefs, "PREFS_FILE", str(prefs_file))

    assert prefs.load_prefs() == {}
    assert json.loads(prefs_file.read_text(encoding="utf-8")) == {}


def test_load_prefs_invalid_json_returns_empty(monkeypatch, tmp_path):
    prefs_file = tmp_path / "user_prefs.json"
    prefs_file.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(prefs, "PREFS_FILE", str(prefs_file))

    assert prefs.load_prefs() == {}


def test_load_prefs_non_object_json_returns_empty(monkeypatch, tmp_path):
    prefs_file = tmp_path / "user_prefs.json"
    prefs_file.write_text("[1,2,3]", encoding="utf-8")
    monkeypatch.setattr(prefs, "PREFS_FILE", str(prefs_file))

    assert prefs.load_prefs() == {}


def test_load_prefs_valid_object(monkeypatch, tmp_path):
    prefs_file = tmp_path / "user_prefs.json"
    prefs_file.write_text('{"123":{"lab_name":"LAB-X"}}', encoding="utf-8")
    monkeypatch.setattr(prefs, "PREFS_FILE", str(prefs_file))

    assert prefs.load_prefs() == {"123": {"lab_name": "LAB-X"}}
