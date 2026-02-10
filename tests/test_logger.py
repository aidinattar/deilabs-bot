from deilabs_bot.logger import Logger


def test_logger_does_not_raise_when_log_file_is_not_writable(monkeypatch):
    class DummyExc(OSError):
        pass

    def _raise(*args, **kwargs):
        raise DummyExc("permission denied")

    monkeypatch.setattr("builtins.open", _raise)

    # Must not raise: logging failures should not break bot/cli flows.
    Logger.log("test_event", "test message", user_id="u1")
