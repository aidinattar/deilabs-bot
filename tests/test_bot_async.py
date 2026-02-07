import asyncio
import json
from types import SimpleNamespace

from deilabs_bot import bot


class FakeMessage:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text, reply_markup=None):
        self.texts.append(text)

    async def reply_markdown(self, text, reply_markup=None):
        self.texts.append(text)


class FakeUser:
    def __init__(self, user_id=123, username="aidin", first_name="Aidin"):
        self.id = user_id
        self.username = username
        self.first_name = first_name


class FakeTGFile:
    def __init__(self, payload):
        self.payload = payload

    async def download_to_drive(self, custom_path):
        with open(custom_path, "w", encoding="utf-8") as f:
            json.dump(self.payload, f)


class FakeBot:
    def __init__(self, payload):
        self.payload = payload
        self.sent_messages = []

    async def get_file(self, file_id):
        return FakeTGFile(self.payload)

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent_messages.append((chat_id, text))


class FakeQuery:
    def __init__(self, user_id, data):
        self.from_user = FakeUser(user_id=user_id)
        self.data = data
        self.edits = []
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, parse_mode=None, reply_markup=None):
        self.edits.append(text)


class ImmediateLoop:
    async def run_in_executor(self, executor, func):
        return func()


def _build_update_and_context(payload=None, user_id=123):
    msg = FakeMessage()
    user = FakeUser(user_id=user_id)
    doc = None
    if payload is not None:
        doc = SimpleNamespace(
            file_size=1024,
            file_name=f"auth_{user_id}.json",
            file_unique_id="ABC123",
            file_id="FILEID",
        )
    update = SimpleNamespace(
        effective_user=user,
        message=SimpleNamespace(
            reply_text=msg.reply_text,
            reply_markdown=msg.reply_markdown,
            document=doc,
        ),
    )
    update.message._collector = msg
    context = SimpleNamespace(bot=FakeBot(payload or {}), args=[])
    return update, context, msg


def _build_callback_update(user_id, data):
    query = FakeQuery(user_id=user_id, data=data)
    update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
    context = SimpleNamespace(bot=FakeBot(payload={}), args=[])
    return update, context, query


def test_status_cmd_logs_and_updates(monkeypatch):
    update, context, msg = _build_update_and_context()
    calls = {"events": [], "current": []}

    monkeypatch.setattr(bot, "resolve_lab", lambda uid: "LAB-TEST")
    monkeypatch.setattr(bot, "run_status", lambda uid, lab: "You are already inside the lab.")
    monkeypatch.setattr(bot.asyncio, "get_running_loop", lambda: ImmediateLoop())
    monkeypatch.setattr(bot, "log_status_event", lambda **kwargs: calls["events"].append(kwargs))
    monkeypatch.setattr(bot, "update_current_status", lambda **kwargs: calls["current"].append(kwargs))

    asyncio.run(bot.status_cmd(update, context))

    assert msg.texts[0] == "Checking your current lab status..."
    assert "already inside" in msg.texts[1]
    assert calls["events"][0]["command"] == "status"
    assert calls["current"][0]["status"] == "inside"


def test_punch_cmd_logs_and_updates(monkeypatch):
    update, context, msg = _build_update_and_context()
    calls = {"events": [], "current": []}

    monkeypatch.setattr(bot, "resolve_lab", lambda uid: "LAB-PUNCH")
    monkeypatch.setattr(
        bot,
        "run_ensure_presence",
        lambda uid, lab: f"Presence logged successfully for lab: {lab}",
    )
    monkeypatch.setattr(bot.asyncio, "get_running_loop", lambda: ImmediateLoop())
    monkeypatch.setattr(bot, "log_status_event", lambda **kwargs: calls["events"].append(kwargs))
    monkeypatch.setattr(bot, "update_current_status", lambda **kwargs: calls["current"].append(kwargs))

    asyncio.run(bot.punch_cmd(update, context))

    assert "Ensuring presence in lab" in msg.texts[0]
    assert "Presence logged successfully" in msg.texts[1]
    assert calls["events"][0]["command"] == "punch"
    assert calls["events"][0]["success"] is True
    assert calls["current"][0]["status"] == "inside"
    assert calls["current"][0]["lab_name"] == "LAB-PUNCH"


def test_exit_cmd_logs_and_updates(monkeypatch):
    update, context, msg = _build_update_and_context()
    calls = {"events": [], "current": []}

    monkeypatch.setattr(bot, "resolve_lab", lambda uid: "LAB-EXIT")
    monkeypatch.setattr(bot, "run_exit", lambda uid, lab: "You have exited the lab.")
    monkeypatch.setattr(bot.asyncio, "get_running_loop", lambda: ImmediateLoop())
    monkeypatch.setattr(bot, "log_status_event", lambda **kwargs: calls["events"].append(kwargs))
    monkeypatch.setattr(bot, "update_current_status", lambda **kwargs: calls["current"].append(kwargs))

    asyncio.run(bot.exit_cmd(update, context))

    assert msg.texts[0] == "Trying to leave the lab..."
    assert msg.texts[1] == "You have exited the lab."
    assert calls["events"][0]["command"] == "exit"
    assert calls["events"][0]["success"] is True
    assert calls["current"][0]["status"] == "outside"
    assert calls["current"][0]["lab_name"] == ""


def test_upload_document_valid_session(monkeypatch, tmp_path):
    payload = {"cookies": [{"domain": ".dei.unipd.it"}]}
    update, context, msg = _build_update_and_context(payload=payload, user_id=999)

    monkeypatch.setattr(bot, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(bot, "AUTH_DIR", tmp_path / "auth")
    upload_calls = []
    monkeypatch.setattr(bot, "log_session_upload", lambda **kwargs: upload_calls.append(kwargs))

    asyncio.run(bot.upload_document(update, context))

    auth_file = tmp_path / "auth" / "auth_999.json"
    assert auth_file.exists()
    assert "Session updated successfully" in msg.texts[-1]
    assert len(upload_calls) == 1


def test_upload_document_rejects_invalid_session(monkeypatch, tmp_path):
    payload = {"cookies": [{"domain": ".example.com"}]}
    update, context, msg = _build_update_and_context(payload=payload, user_id=1001)

    monkeypatch.setattr(bot, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(bot, "AUTH_DIR", tmp_path / "auth")
    upload_calls = []
    monkeypatch.setattr(bot, "log_session_upload", lambda **kwargs: upload_calls.append(kwargs))

    asyncio.run(bot.upload_document(update, context))

    auth_file = tmp_path / "auth" / "auth_1001.json"
    assert not auth_file.exists()
    assert "does not look like a DeiLabs session" in msg.texts[-1]
    assert upload_calls == []


def test_morning_ping_job_sends_to_known_users(monkeypatch):
    fake_bot = FakeBot(payload={})
    context = SimpleNamespace(bot=fake_bot)
    monkeypatch.setattr(bot, "get_known_users", lambda: {"10": "u10", "11": None})

    asyncio.run(bot.morning_ping_job(context))

    assert len(fake_bot.sent_messages) == 2
    assert fake_bot.sent_messages[0][0] == 10


def test_midday_status_job_calls_auto_update(monkeypatch):
    context = SimpleNamespace(bot=FakeBot(payload={}))
    monkeypatch.setattr(bot, "get_known_users", lambda: {"20": "u20", "21": None})
    calls = []

    async def fake_auto(uid, username):
        calls.append((uid, username))

    monkeypatch.setattr(bot, "_auto_status_update", fake_auto)
    asyncio.run(bot.midday_status_job(context))

    assert ("20", "u20") in calls
    assert ("21", None) in calls


def test_admin_cmd_requires_authorization(monkeypatch):
    update, context, msg = _build_update_and_context(user_id=50)
    monkeypatch.setattr(bot, "ADMIN_USER_IDS", {"1"})

    asyncio.run(bot.admin_cmd(update, context))

    assert msg.texts[-1] == "Not authorized."


def test_admin_action_ping(monkeypatch):
    update, context, query = _build_callback_update(user_id=1, data="admin:ping")
    monkeypatch.setattr(bot, "ADMIN_USER_IDS", {"1"})

    async def fake_ping(_context):
        return {"total": 3, "sent": 3, "failed": 0, "skipped": 0}

    monkeypatch.setattr(bot, "morning_ping_job", fake_ping)
    asyncio.run(bot.admin_action_button(update, context))

    assert "Reminder sent." in query.edits[-1]


def test_admin_action_status_table(monkeypatch):
    update, context, query = _build_callback_update(user_id=1, data="admin:status")
    monkeypatch.setattr(bot, "ADMIN_USER_IDS", {"1"})
    monkeypatch.setattr(
        bot,
        "list_current_status_snapshot",
        lambda: [("10", "u10", "inside", "LAB-A", "2026-02-07T09:00:00", "2026-02-07 09:00:01")],
    )

    asyncio.run(bot.admin_action_button(update, context))

    assert "Current status snapshot" in query.edits[-1]
    assert "LAB-A" in query.edits[-1]
    assert "filter=all" in query.edits[-1]


def test_admin_action_status_filter_and_pagination(monkeypatch):
    update, context, query = _build_callback_update(user_id=1, data="adminstatus:inside:0")
    monkeypatch.setattr(bot, "ADMIN_USER_IDS", {"1"})
    monkeypatch.setattr(bot, "STATUS_PAGE_SIZE", 1)
    monkeypatch.setattr(
        bot,
        "list_current_status_snapshot",
        lambda: [
            ("10", "u10", "inside", "LAB-I", "2026-02-07T09:00:00", "2026-02-07 09:00:01"),
            ("20", "u20", "outside", "LAB-O", None, "2026-02-07 09:00:02"),
        ],
    )

    asyncio.run(bot.admin_action_button(update, context))

    assert "filter=inside" in query.edits[-1]
    assert "total=1" in query.edits[-1]
    assert "LAB-I" in query.edits[-1]
    assert "LAB-O" not in query.edits[-1]
