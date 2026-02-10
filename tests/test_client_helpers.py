import deilabs_bot.client as client_module
from deilabs_bot.client import DeilabsClient
from deilabs_bot.config import DeilabsConfig


class FakePage:
    def __init__(self, url: str, html: str):
        self.url = url
        self._html = html

    def content(self) -> str:
        return self._html


def _client(user_id: str = "123") -> DeilabsClient:
    return DeilabsClient(DeilabsConfig(user_id=user_id, lab_name="LAB-X"))


def test_session_expired_message_contains_login_and_upload_steps():
    client = _client("174325172")
    msg = client._session_expired_message()
    assert "deilabs login --user-id 174325172" in msg
    assert "auth_174325172.json" in msg


def test_is_session_expired_detects_redirect_url():
    client = _client()
    page = FakePage("https://deilabs.dei.unipd.it/login", "<html></html>")
    assert client._is_session_expired(page) is True


def test_is_session_expired_detects_expired_banner_in_html():
    client = _client()
    page = FakePage(
        "https://deilabs.dei.unipd.it/laboratory_in_outs",
        "<div>Sorry, your session seems to have expired. Please login again.</div>",
    )
    assert client._is_session_expired(page) is True


def test_is_session_expired_false_for_normal_page():
    client = _client()
    page = FakePage(
        "https://deilabs.dei.unipd.it/laboratory_in_outs",
        "<div>You are not in any lab.</div>",
    )
    assert client._is_session_expired(page) is False


def test_is_retryable_navigation_error_detects_ns_interrupt():
    client = _client()
    err = RuntimeError("Page.goto: NS_ERROR_NET_INTERRUPT")
    assert client._is_retryable_navigation_error(err) is True


def test_open_lab_page_retries_on_transient_error(monkeypatch):
    client = _client()
    client.nav_retries = 2
    client.nav_retry_delay_ms = 10

    class FakePage:
        def __init__(self):
            self.calls = 0
            self.waits = []

        def goto(self, url, wait_until, timeout):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("Page.goto: NS_ERROR_NET_INTERRUPT")
            return None

        def wait_for_timeout(self, value):
            self.waits.append(value)

    page = FakePage()
    monkeypatch.setattr(client_module, "PlaywrightError", RuntimeError)
    monkeypatch.setattr(client_module, "PlaywrightTimeoutError", TimeoutError)
    monkeypatch.setattr(client_module.Logger, "log", lambda *args, **kwargs: None)

    client._open_lab_page(page)

    assert page.calls == 2
    assert page.waits == [10]


def test_open_lab_page_does_not_retry_non_retryable_error(monkeypatch):
    client = _client()
    client.nav_retries = 3

    class FakePage:
        def __init__(self):
            self.calls = 0

        def goto(self, url, wait_until, timeout):
            self.calls += 1
            raise RuntimeError("Page.goto: Protocol error")

        def wait_for_timeout(self, value):
            raise AssertionError("No retry delay expected")

    page = FakePage()
    monkeypatch.setattr(client_module, "PlaywrightError", RuntimeError)
    monkeypatch.setattr(client_module, "PlaywrightTimeoutError", TimeoutError)
    monkeypatch.setattr(client_module.Logger, "log", lambda *args, **kwargs: None)

    try:
        client._open_lab_page(page)
    except RuntimeError as exc:
        assert "Protocol error" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")

    assert page.calls == 1
